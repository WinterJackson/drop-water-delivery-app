import { auth } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Streams a CSV export from FastAPI to the browser.
 *
 * A download is the one case a plain `<a href>` cannot go through a Server
 * Component: the browser has to make the request itself to get a file. So this
 * route handler stands in — it attaches the bearer token server-side, exactly
 * like `lib/api/server.ts`, and the token still never reaches client code.
 *
 * It is a pass-through, not a second API: the report is chosen and authorised
 * entirely by the backend, which requires `data.export`, records the row count
 * in the audit log, and is the only thing that decides what the file contains.
 */

const BACKEND = process.env.BACKEND_BASE_URL;

const REPORTS = new Set(["revenue", "vendors", "riders"]);

export async function GET(request: NextRequest) {
  if (!BACKEND) {
    return NextResponse.json({ error: "Backend is not configured." }, { status: 500 });
  }

  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  const report = request.nextUrl.searchParams.get("report") ?? "revenue";
  const days = Number(request.nextUrl.searchParams.get("days") ?? 30);

  // Validated here as well so a malformed query is a 400 rather than an opaque
  // upstream error. The backend validates independently — this is convenience,
  // not the control.
  if (!REPORTS.has(report) || !Number.isInteger(days) || days < 1 || days > 365) {
    return NextResponse.json({ error: "Unknown report or range." }, { status: 400 });
  }

  const upstream = await fetch(
    `${BACKEND}/api/admin/analytics/export?report=${report}&days=${days}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );

  if (!upstream.ok) {
    // Surface the refusal rather than a broken download. A 403 here means the
    // caller lacks `data.export`.
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "The export was refused." },
      { status: upstream.status },
    );
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition":
        upstream.headers.get("content-disposition") ??
        `attachment; filename="drop-${report}-${days}d.csv"`,
      // Business figures: no intermediary should keep a copy.
      "Cache-Control": "no-store",
    },
  });
}
