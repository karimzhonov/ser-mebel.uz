import { useEffect, useState, type ComponentType } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Boxes,
  Brush,
  Calculator,
  ChevronDown,
  Factory,
  Hammer,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Package,
  Paintbrush,
  PhoneCall,
  Ruler,
  Send,
  Settings2,
  Sun,
  Upload,
  Download,
  Users,
  UserCog,
  X,
  BookOpen,
} from "lucide-react";
import logoWide from "@/assets/logo-wide.png";
import { useAuth } from "@/auth/AuthContext";
import { cn } from "@/lib/cn";
import { phone } from "@/lib/format";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  perm?: string;
  superuser?: boolean;
}

// Same sections and permissions as the admin sidebar (backend/core/sidebars.py).
const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "",
    items: [{ to: "/", label: "Bosh sahifa", icon: LayoutDashboard }],
  },
  {
    title: "Sotuv",
    items: [
      { to: "/call-center", label: "Call-center", icon: PhoneCall, perm: "call_center.view_invoice" },
      { to: "/clients", label: "Mijozlar", icon: Users, perm: "client.view_client" },
    ],
  },
  {
    title: "O'lchov",
    items: [
      { to: "/meterings", label: "O'lchovlar", icon: Ruler, perm: "metering.view_metering" },
      { to: "/designs", label: "Dizayn", icon: Brush, perm: "design.view_design" },
      { to: "/prices", label: "Narx hisoblash", icon: Calculator, perm: "price.view_price" },
      { to: "/catalog", label: "Mahsulotlar", icon: Boxes, perm: "price.view_inventorytype" },
    ],
  },
  {
    title: "Buyurtmalar",
    items: [
      { to: "/orders", label: "Buyurtmalar", icon: Package, perm: "order.view_order" },
      { to: "/production/detailing", label: "Detalirovka", icon: BookOpen, perm: "detailing.view_detailing" },
      { to: "/production/rover", label: "Rover", icon: Settings2, perm: "rover.view_rover" },
      { to: "/production/painter", label: "Molyar", icon: Paintbrush, perm: "painter.view_painter" },
      { to: "/production/assembly", label: "Yig'ish / O'rnatish", icon: Hammer, perm: "assembly.view_assembly" },
      { to: "/factories", label: "Zavodlar", icon: Factory, perm: "order.view_factory" },
    ],
  },
  {
    title: "Buxgalteriya",
    items: [
      { to: "/accounting/income", label: "Kirimlar", icon: Download, perm: "accounting.view_income" },
      { to: "/accounting/expense", label: "Chiqimlar", icon: Upload, perm: "accounting.view_expense" },
    ],
  },
  {
    title: "Tizim",
    items: [{ to: "/users", label: "Xodimlar", icon: UserCog, superuser: true }],
  },
];

// Bottom tab bar on phones: the four places staff open most.
const MOBILE_TABS: NavItem[] = [
  { to: "/", label: "Bosh sahifa", icon: LayoutDashboard },
  { to: "/orders", label: "Buyurtmalar", icon: Package, perm: "order.view_order" },
  { to: "/meterings", label: "O'lchovlar", icon: Ruler, perm: "metering.view_metering" },
  { to: "/call-center", label: "Qo'ng'iroqlar", icon: PhoneCall, perm: "call_center.view_invoice" },
];

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* ignore */
    }
  }, [dark]);
  return [dark, setDark] as const;
}

export function AppLayout() {
  const { user, can, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useTheme();
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);

  const visible = (item: NavItem) => (item.superuser ? user?.is_superuser : !item.perm || can(item.perm));
  const sections = NAV.map((s) => ({ ...s, items: s.items.filter(visible) })).filter((s) => s.items.length);

  const sidebar = (
    <div className="flex h-full flex-col">
      <NavLink to="/" className="block px-5 pb-3 pt-5" title="SerMebel">
        <img src={logoWide} alt="SerMebel" className="h-auto w-full max-w-[200px]" />
      </NavLink>
      <nav className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {sections.map((section) => (
          <NavSection key={section.title || "main"} title={section.title} items={section.items} />
        ))}
      </nav>
      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-3 rounded-xl px-2 py-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-200 text-sm font-semibold text-brand-900">
            {(user?.name || "?").slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-white">{user?.name || "Ismsiz"}</div>
            <div className="truncate text-xs text-accent-200/60">{phone(user?.phone)}</div>
          </div>
        </div>
        <div className="mt-1 grid grid-cols-3 gap-1">
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center justify-center rounded-lg py-2 text-accent-200/70 hover:bg-white/10 hover:text-accent-200"
            title="Mavzu"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <a
            href={user?.telegram_link}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "flex items-center justify-center rounded-lg py-2 hover:bg-white/10",
              user?.telegram_id ? "text-sky-300" : "text-accent-200/70",
            )}
            title={user?.telegram_id ? "Telegram ulangan" : "Telegramni ulash"}
          >
            <Send className="h-4 w-4" />
          </a>
          <button
            onClick={logout}
            className="flex items-center justify-center rounded-lg py-2 text-accent-200/70 hover:bg-rose-500/20 hover:text-rose-200"
            title="Chiqish"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 bg-brand-900 lg:block">
        {sidebar}
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-slate-950/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-brand-900 shadow-pop">
            <button className="absolute right-3 top-4 rounded-lg p-2 text-accent-200" onClick={() => setOpen(false)}>
              <X className="h-5 w-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 bg-brand-900 px-4 lg:hidden">
        <button onClick={() => setOpen(true)} className="-ml-1 rounded-lg p-2 text-accent-200">
          <Menu className="h-5 w-5" />
        </button>
        <img src={logoWide} alt="SerMebel" className="h-8 w-auto" />
      </header>

      <main className="px-4 pb-24 pt-5 sm:px-6 lg:ml-64 lg:px-8 lg:pb-10 lg:pt-8">
        <div className="mx-auto max-w-[1600px]">
          <Outlet />
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-slate-200/70 bg-white/90 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 lg:hidden">
        {MOBILE_TABS.filter(visible).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
                isActive ? "text-brand-800 dark:text-accent-200" : "text-slate-500",
              )
            }
          >
            <item.icon className="h-5 w-5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function NavSection({ title, items }: { title: string; items: NavItem[] }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div>
      {title && (
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="mb-1 flex w-full items-center justify-between px-3 text-[11px] font-semibold uppercase tracking-wider text-accent-200/50"
        >
          {title}
          <ChevronDown className={cn("h-3.5 w-3.5 transition", collapsed && "-rotate-90")} />
        </button>
      )}
      {!collapsed && (
        <ul className="space-y-0.5">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
                    isActive
                      ? "bg-accent-200 text-brand-900 shadow-sm"
                      : "text-white/75 hover:bg-white/10 hover:text-white",
                  )
                }
              >
                <item.icon className="h-[18px] w-[18px] shrink-0" />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

