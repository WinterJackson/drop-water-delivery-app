/**
 * Offline SQLite database for caching orders and queuing actions.
 * Uses dynamic import so expo-sqlite doesn't crash at module load
 * when the native module isn't available (e.g., Expo Go).
 */

let _db: any = null;
let dbFailed = false;

const getSQLite = async () => {
    try {
        return await import('expo-sqlite');
    } catch {
        return null;
    }
};

export const getDB = async () => {
    if (dbFailed) return null;
    if (_db) return _db;
    const SQLite = await getSQLite();
    if (!SQLite) return null;
    try {
        _db = await SQLite.openDatabaseAsync('drop_offline.db');
        return _db;
    } catch (e) {
        if (__DEV__) console.warn('[getDB] Failed to open database:', e);
        return null;
    }
}

export const initDB = async () => {
    const db = await getDB();
    if (!db) {
        if (__DEV__) console.warn('[initDB] SQLite not available — offline features disabled.');
        return;
    }
    try {
        // Money is TEXT here, exactly as it is NUMERIC in Postgres and a decimal
        // string on the wire.
        //
        // `total_amount` and `delivery_fee` were `REAL`. The platform is emphatic
        // about this everywhere else — `utils/money.py` serialises a Decimal to a
        // string, `utils/money.ts` does the arithmetic in integer cents via
        // `BigInt`, and a test walks every schema and every response dict to stop
        // a float reappearing — and the chain broke at the last link, in the
        // offline cache. A value round-tripped through a binary float is no longer
        // the figure the ledger holds, and this is the copy a rider reads when
        // they are offline, which is precisely when they cannot check it against
        // anything. `formatMoney` would also have rendered `120` where the server
        // said `"120.00"`.
        //
        // Coordinates stay REAL: they are measurements, not money.
        await db.execAsync(`
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                vendor_id TEXT,
                customer_id TEXT,
                delivery_address TEXT,
                phone TEXT,
                lat_from REAL,
                lng_from REAL,
                lat REAL,
                lng REAL,
                total_amount TEXT,
                order_status TEXT,
                payment_status TEXT,
                delivery_fee TEXT,
                updated_at TEXT
            );
        `);

        // --- money-as-text migration ---
        // `CREATE TABLE IF NOT EXISTS` checks the table name and not its column
        // types, so a handset that already has this app installed keeps the REAL
        // columns and keeps the defect. SQLite has no ALTER COLUMN TYPE, and this
        // table is a *cache* of server state — it is rebuilt from the next
        // successful fetch — so the honest migration is to drop and let it refill
        // rather than to convert values that are already lossy.
        //
        // `offline_actions` is deliberately untouched by this: it holds work the
        // rider has done and not yet synced, which is not reconstructible from
        // anywhere.
        const orderCols = (await db.getAllAsync(`PRAGMA table_info(orders)`)) as any[];
        const moneyIsFloat = orderCols.some(
            (c: any) => (c.name === 'total_amount' || c.name === 'delivery_fee') && String(c.type).toUpperCase() === 'REAL'
        );
        if (moneyIsFloat) {
            await db.execAsync(`DROP TABLE IF EXISTS orders;`);
            await db.execAsync(`
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    vendor_id TEXT,
                    customer_id TEXT,
                    delivery_address TEXT,
                    phone TEXT,
                    lat_from REAL,
                    lng_from REAL,
                    lat REAL,
                    lng REAL,
                    total_amount TEXT,
                    order_status TEXT,
                    payment_status TEXT,
                    delivery_fee TEXT,
                    updated_at TEXT
                );
            `);
            if (__DEV__) console.log('[initDB] Rebuilt the offline order cache with money as TEXT.');
        }

        // --- offline_actions migration ---
        // CREATE TABLE IF NOT EXISTS only checks the table NAME, not its columns. Devices
        // that already have this app installed have an offline_actions table from before
        // the row_id surrogate key existed (id TEXT PRIMARY KEY only). Left alone, every
        // queueOfflineAction() call on those devices throws "no such column: row_id",
        // silently swallowed by its catch block — offline queueing goes dark with zero
        // user-facing signal. Detect the old schema and migrate forward instead.
        const existingCols = await db.getAllAsync(`PRAGMA table_info(offline_actions)`) as any[];
        const hasRowId = existingCols.some((c: any) => c.name === 'row_id');

        if (existingCols.length > 0 && !hasRowId) {
            let legacyRows: any[] = [];
            try {
                legacyRows = await db.getAllAsync(`SELECT * FROM offline_actions`) as any[];
            } catch {
                legacyRows = [];
            }

            await db.execAsync(`DROP TABLE IF EXISTS offline_actions;`);
            await db.execAsync(`
                CREATE TABLE IF NOT EXISTS offline_actions (
                    row_id TEXT PRIMARY KEY,
                    id TEXT,
                    type TEXT,
                    payload TEXT,
                    created_at TEXT
                );
            `);

            if (legacyRows.length > 0) {
                const migrateStmt = await db.prepareAsync(`
                    INSERT OR REPLACE INTO offline_actions (row_id, id, type, payload, created_at)
                    VALUES ($row_id, $id, $type, $payload, $created_at)
                `);
                try {
                    for (const row of legacyRows) {
                        await migrateStmt.executeAsync({
                            $row_id: `${row.id}:migrated:${row.created_at || Date.now()}`,
                            $id: row.id,
                            $type: row.type,
                            $payload: row.payload,
                            $created_at: row.created_at,
                        });
                    }
                } finally {
                    await migrateStmt.finalizeAsync();
                }
                if (__DEV__) console.log(`[initDB] Migrated ${legacyRows.length} queued offline action(s) to new schema.`);
            }
        } else {
            await db.execAsync(`
                CREATE TABLE IF NOT EXISTS offline_actions (
                    row_id TEXT PRIMARY KEY,
                    id TEXT,
                    type TEXT,
                    payload TEXT,
                    created_at TEXT
                );
            `);
        }

        // --- replay bookkeeping migration ---
        // `attempts`, `last_error` and `needs_attention` back the backoff and the
        // Pending Sync screen (`services/offlineQueue.ts`). Added with ALTER
        // rather than a table rebuild: these rows are a rider's unsynced
        // deliveries, and dropping the table to add a column would destroy the
        // exact data the queue exists to protect.
        const cols = await db.getAllAsync(`PRAGMA table_info(offline_actions)`) as any[];
        const names = new Set(cols.map((c: any) => c.name));
        for (const [column, ddl] of [
            ['attempts', 'ALTER TABLE offline_actions ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0'],
            ['last_error', 'ALTER TABLE offline_actions ADD COLUMN last_error TEXT'],
            ['needs_attention', 'ALTER TABLE offline_actions ADD COLUMN needs_attention INTEGER NOT NULL DEFAULT 0'],
        ] as const) {
            if (!names.has(column)) {
                try {
                    await db.execAsync(ddl);
                } catch (e) {
                    if (__DEV__) console.warn(`[initDB] could not add ${column}:`, e);
                }
            }
        }
    } catch (e: unknown) {
        if (__DEV__ && !(e as Error)?.message?.includes('NullPointerException')) {
            console.warn('[initDB] SQLite init failed (non-fatal):', e);
        }
        _db = null; // Prevent subsequent calls from throwing if initialization fails
        dbFailed = true; // Mark as failed to prevent retrying
    }
}

export const saveOrdersLocal = async (orders: any[]) => {
    const db = await getDB();
    if (!db) return;

    try {
        const statement = await db.prepareAsync(`
            INSERT OR REPLACE INTO orders (
                id, vendor_id, customer_id, delivery_address, phone, lat_from, lng_from, lat, lng, 
                total_amount, order_status, payment_status, delivery_fee, updated_at
            ) VALUES ($id, $vendor_id, $customer_id, $delivery_address, $phone, $lat_from, $lng_from, $lat, $lng, $total_amount, $order_status, $payment_status, $delivery_fee, $updated_at)
        `);

        for (let o of orders) {
            await statement.executeAsync({
                $id: o.id,
                $vendor_id: o.vendor_id,
                $customer_id: o.customer_id,
                $delivery_address: o.delivery_address,
                $phone: o.phone,
                $lat_from: o.lat_from,
                $lng_from: o.lng_from,
                $lat: o.lat,
                $lng: o.lng,
                // Bound as text, never as a number. The server sends a decimal
                // string and it is stored unchanged; coercing here rather than
                // relying on SQLite's column affinity means a value that somehow
                // arrives as a number is at least recorded as what it was, instead
                // of becoming `"120"` where the server said `"120.00"`.
                $total_amount: o.total_amount == null ? null : String(o.total_amount),
                $order_status: o.order_status,
                $payment_status: o.payment_status,
                $delivery_fee: o.delivery_fee == null ? null : String(o.delivery_fee),
                $updated_at: o.updated_at
            });
        }
        await statement.finalizeAsync();
    } catch (e) {
        if (__DEV__) console.warn('[saveOrdersLocal] SQLite operation failed (non-fatal):', e);
    }
}

export const getOrdersLocal = async () => {
    const db = await getDB();
    if (!db) return [];
    try {
        const result = await db.getAllAsync('SELECT * FROM orders ORDER BY updated_at DESC');
        return result;
    } catch (e) {
        if (__DEV__) console.warn('[getOrdersLocal] SQLite failed:', e);
        return [];
    }
}

// --- OFFLINE ACTION QUEUE ---

export const queueOfflineAction = async (id: string, type: string, payload: string) => {
    const db = await getDB();
    if (!db) return;
    const created_at = new Date().toISOString();
    const row_id = `${id}:${Date.now()}`;
    try {
        await db.runAsync(
            `INSERT OR REPLACE INTO offline_actions (row_id, id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)`,
            [row_id, id, type, payload, created_at]
        );
    } catch (e) {
        if (__DEV__) console.warn('[queueOfflineAction] SQLite failed:', e);
    }
}

export const getQueuedActions = async () => {
    const db = await getDB();
    if (!db) return [];
    try {
        return await db.getAllAsync('SELECT * FROM offline_actions ORDER BY created_at ASC');
    } catch (e: unknown) {
        if (__DEV__ && !(e as Error)?.message?.includes('NullPointerException')) {
            console.warn('[getQueuedActions] SQLite failed:', e);
        }
        return [];
    }
}

export const removeQueuedAction = async (id: string) => {
    const db = await getDB();
    if (!db) return;
    try {
        await db.runAsync(`DELETE FROM offline_actions WHERE row_id = ?`, [id]);
    } catch (e) {
        if (__DEV__) console.warn('[removeQueuedAction] SQLite failed:', e);
    }
}

/**
 * Wipe every cached row belonging to the signed-out rider.
 *
 * `orders` holds customer delivery addresses and phone numbers, and unlike the
 * React Query cache it is on disk — it outlived sign-out entirely, so the next
 * rider to use a shared device inherited the previous rider's manifest. Queued
 * offline actions go too: they carry the old rider's credentials-scoped intent
 * and replaying them under a new session would attribute the work to the wrong
 * person.
 */
export const clearOfflineData = async () => {
    const db = await getDB();
    if (!db) return;
    try {
        await db.execAsync('DELETE FROM orders; DELETE FROM offline_actions;');
    } catch (e) {
        if (__DEV__) console.warn('[clearOfflineData] SQLite failed:', e);
    }
}
