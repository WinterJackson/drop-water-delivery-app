import {
  ArrowLeftRight,
  Gauge,
  Boxes,
  FileWarning,
  BadgeCheck,
  Banknote,
  BarChart3,
  ClipboardList,
  LayoutDashboard,
  LifeBuoy,
  // Aliased: lucide exports this as `Map`, which would shadow the global
  // `Map` constructor for the whole module.
  Map as MapIcon,
  Megaphone,
  PackageSearch,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Store,
  Truck,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { NavBadge } from "@/lib/nav-counts";
import { PERMISSIONS, type Permission } from "@/lib/permissions";

/**
 * Every destination in the console, declared once.
 *
 * The sidebar, the mobile drawer, the bottom tab bar and the header breadcrumb
 * all render from this list. Three hand-maintained copies of the same routes is
 * how a page ends up reachable from the desktop nav and invisible on a phone —
 * and how a capability check gets added in one place and forgotten in the other
 * two.
 *
 * `permission` hides an entry the caller cannot use. That is **courtesy, not
 * access control**: every route is enforced again by `require_admin(...)` on the
 * backend, and that check is the only one that decides anything.
 */

export type NavItem = {
  href: string;
  label: string;
  /** Used where horizontal space is tight — the bottom bar's accessible name. */
  short: string;
  icon: LucideIcon;
  /** Hidden when the caller lacks it. Absent means "any administrator". */
  permission?: Permission;
  /**
   * Lower sorts earlier in the bottom tab bar. Only the first few survive; the
   * rest stay one tap away behind "More", so nothing is ever unreachable on a
   * phone.
   */
  mobilePriority?: number;
  /** One line of context, shown in the drawer and as the breadcrumb subtitle. */
  blurb?: string;
  /**
   * Which queue depth to show beside this entry, if the caller may see it.
   * Only queues where a number means "somebody has to act" get one — a badge on
   * a page that is merely a list trains people to ignore all of them.
   */
  badge?: NavBadge;
};

export type NavSection = { title: string; items: NavItem[] };

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [
      {
        href: "/",
        label: "Dashboard",
        short: "Home",
        icon: LayoutDashboard,
        permission: PERMISSIONS.analyticsRead,
        mobilePriority: 1,
        blurb: "What needs attention today.",
      },
      {
        href: "/analytics",
        label: "Analytics",
        short: "Insights",
        icon: BarChart3,
        permission: PERMISSIONS.analyticsRead,
        mobilePriority: 7,
        blurb: "Revenue, demand, retention and unit economics.",
      },
    ],
  },
  {
    title: "Operations",
    items: [
      {
        href: "/operations/orders",
        label: "Orders",
        short: "Orders",
        icon: ClipboardList,
        permission: PERMISSIONS.ordersRead,
        mobilePriority: 2,
        badge: "orders_stuck",
        blurb: "Live board, opening on the ones that are stuck.",
      },
      {
        href: "/operations/kyc",
        label: "Rider verification",
        short: "Riders",
        icon: BadgeCheck,
        permission: PERMISSIONS.ridersRead,
        mobilePriority: 4,
        badge: "rider_kyc",
        blurb: "Riders cannot accept a delivery until this is done.",
      },
      {
        href: "/operations/map",
        label: "Live map",
        short: "Map",
        icon: MapIcon,
        permission: PERMISSIONS.geoView,
        mobilePriority: 6,
        blurb: "Where riders, stores, demand and live orders actually are.",
      },
      {
        href: "/operations/catalogue",
        label: "Catalogue",
        short: "Products",
        icon: Boxes,
        permission: PERMISSIONS.vendorsRead,
        mobilePriority: 10,
        blurb: "Every product on sale, and the prices that look wrong.",
      },
      {
        href: "/operations/vendors",
        label: "Vendor verification",
        short: "Stores",
        icon: Store,
        permission: PERMISSIONS.vendorsRead,
        mobilePriority: 9,
        badge: "vendor_verification",
        blurb: "Confirm a store's paperwork before it trades.",
      },
      {
        href: "/operations/disputes",
        label: "Bottle disputes",
        short: "Disputes",
        icon: PackageSearch,
        permission: PERMISSIONS.disputesRead,
        mobilePriority: 10,
        badge: "disputes",
        blurb: "Deliveries where the bottle count did not agree.",
      },
    ],
  },
  {
    title: "Support",
    items: [
      {
        href: "/support",
        label: "Support inbox",
        short: "Support",
        icon: LifeBuoy,
        permission: PERMISSIONS.supportRead,
        mobilePriority: 3,
        badge: "support",
        blurb: "Questions raised from the three apps, oldest first.",
      },
    ],
  },
  {
    title: "People",
    items: [
      {
        href: "/people/performance",
        label: "Performance",
        short: "Perf",
        icon: Gauge,
        permission: PERMISSIONS.ridersRead,
        mobilePriority: 11,
        blurb: "Who is delivering, who is selling, and how reliably.",
      },
      {
        href: "/people/customers",
        label: "Customers",
        short: "Customers",
        icon: UserRound,
        permission: PERMISSIONS.customersRead,
        mobilePriority: 11,
        blurb: "Everyone who orders water.",
      },
      {
        href: "/people/riders",
        label: "Riders",
        short: "Riders",
        icon: Truck,
        permission: PERMISSIONS.ridersRead,
        mobilePriority: 12,
        blurb: "Everyone who delivers it.",
      },
      {
        href: "/people/vendors",
        label: "Vendors",
        short: "Vendors",
        icon: Store,
        permission: PERMISSIONS.vendorsRead,
        mobilePriority: 13,
        blurb: "Every store on the platform.",
      },
    ],
  },
  {
    title: "Finance",
    items: [
      {
        href: "/finance/payouts",
        label: "Payouts",
        short: "Payouts",
        icon: Banknote,
        permission: PERMISSIONS.financeRead,
        mobilePriority: 5,
        badge: "payouts",
        blurb: "Vendors and riders waiting to be paid.",
      },
      {
        href: "/finance/transactions",
        label: "Transactions",
        short: "Ledger",
        icon: ArrowLeftRight,
        permission: PERMISSIONS.financeRead,
        mobilePriority: 8,
        blurb: "Every movement of money, and what the platform kept.",
      },
      {
        href: "/finance/reconciliation",
        label: "Reconciliation",
        short: "Recon",
        icon: FileWarning,
        permission: PERMISSIONS.financeRead,
        mobilePriority: 9,
        badge: "reconciliation",
        blurb: "Payment callbacks that failed — money in, order still pending.",
      },
    ],
  },
  {
    title: "Platform",
    items: [
      {
        href: "/platform/admins",
        label: "Administrators",
        short: "Admins",
        icon: Users,
        permission: PERMISSIONS.adminsManage,
        blurb: "Who can use this console, and what they may do.",
      },
      {
        href: "/platform/audit",
        label: "Audit log",
        short: "Audit",
        icon: ScrollText,
        permission: PERMISSIONS.adminsManage,
        blurb: "Every administrator action, with the reason given.",
      },
      {
        href: "/platform/pricing",
        label: "Pricing & fees",
        short: "Pricing",
        icon: SlidersHorizontal,
        permission: PERMISSIONS.settingsManage,
        blurb: "What the platform charges, and what it keeps. Live in all three apps.",
      },
      {
        href: "/platform/broadcast",
        label: "Broadcast",
        short: "Broadcast",
        icon: Megaphone,
        permission: PERMISSIONS.broadcastSend,
        blurb: "Message a segment. There is no undo.",
      },
      {
        href: "/platform/settings",
        label: "Settings",
        short: "Settings",
        icon: Settings,
        permission: PERMISSIONS.settingsManage,
        blurb: "The switches this deployment is running with.",
      },
    ],
  },
];

/** Flattened, in sidebar order. */
export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

export function visibleSections(permissions: readonly string[]): NavSection[] {
  const held = new Set(permissions);
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.permission || held.has(item.permission)),
  })).filter((section) => section.items.length > 0);
}

/**
 * The handful of destinations that fit across the bottom of a phone.
 *
 * Capped at four so the fifth slot can always be "More" — a tab bar that
 * silently drops the pages someone happens to have permission for is worse than
 * one extra tap.
 */
export function tabBarItems(permissions: readonly string[], limit = 4): NavItem[] {
  const held = new Set(permissions);
  return NAV_ITEMS.filter((item) => item.mobilePriority !== undefined)
    .filter((item) => !item.permission || held.has(item.permission))
    .sort((a, b) => a.mobilePriority! - b.mobilePriority!)
    .slice(0, limit);
}

/**
 * `/` matches only itself; everything else matches its own subtree, so a detail
 * page keeps its parent highlighted.
 */
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The deepest nav entry containing this path, for the header's breadcrumb. */
export function matchItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.filter((item) => isActive(pathname, item.href)).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
}

export function sectionOf(item: NavItem): string | undefined {
  return NAV_SECTIONS.find((section) => section.items.includes(item))?.title;
}
