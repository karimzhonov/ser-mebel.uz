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
  Wrench,
  X,
  BookOpen,
} from "lucide-react";
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
    items: [{ to: "/", label: "Главная", icon: LayoutDashboard }],
  },
  {
    title: "Продажи",
    items: [
      { to: "/call-center", label: "Call-center", icon: PhoneCall, perm: "call_center.view_invoice" },
      { to: "/clients", label: "Клиенты", icon: Users, perm: "client.view_client" },
    ],
  },
  {
    title: "Замер",
    items: [
      { to: "/meterings", label: "Замеры", icon: Ruler, perm: "metering.view_metering" },
      { to: "/designs", label: "Дизайн", icon: Brush, perm: "design.view_design" },
      { to: "/prices", label: "Нарх чиқариш", icon: Calculator, perm: "price.view_price" },
      { to: "/catalog", label: "Товары", icon: Boxes, perm: "price.view_inventorytype" },
    ],
  },
  {
    title: "Заказы",
    items: [
      { to: "/orders", label: "Заказы", icon: Package, perm: "order.view_order" },
      { to: "/production/detailing", label: "Деталировка", icon: BookOpen, perm: "detailing.view_detailing" },
      { to: "/production/rover", label: "Ровер", icon: Settings2, perm: "rover.view_rover" },
      { to: "/production/painter", label: "Моляр", icon: Paintbrush, perm: "painter.view_painter" },
      { to: "/production/assembly", label: "Сборка / Установка", icon: Hammer, perm: "assembly.view_assembly" },
      { to: "/factories", label: "Заводы", icon: Factory, perm: "order.view_factory" },
    ],
  },
  {
    title: "Бухгалтерия",
    items: [
      { to: "/accounting/income", label: "Приходы", icon: Download, perm: "accounting.view_income" },
      { to: "/accounting/expense", label: "Расходы", icon: Upload, perm: "accounting.view_expense" },
    ],
  },
  {
    title: "Система",
    items: [{ to: "/users", label: "Сотрудники", icon: UserCog, superuser: true }],
  },
];

// Bottom tab bar on phones: the four places staff open most.
const MOBILE_TABS: NavItem[] = [
  { to: "/", label: "Главная", icon: LayoutDashboard },
  { to: "/orders", label: "Заказы", icon: Package, perm: "order.view_order" },
  { to: "/meterings", label: "Замеры", icon: Ruler, perm: "metering.view_metering" },
  { to: "/call-center", label: "Звонки", icon: PhoneCall, perm: "call_center.view_invoice" },
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
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-600/30">
          <Wrench className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-900 dark:text-white">Ser Mebel</div>
          <div className="muted text-[11px]">CRM панель</div>
        </div>
      </div>
      <nav className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {sections.map((section) => (
          <NavSection key={section.title || "main"} title={section.title} items={section.items} />
        ))}
      </nav>
      <div className="border-t border-slate-200/70 p-3 dark:border-slate-800">
        <div className="flex items-center gap-3 rounded-xl px-2 py-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700 dark:bg-brand-500/20 dark:text-brand-200">
            {(user?.name || "?").slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.name || "Без имени"}</div>
            <div className="muted truncate text-xs">{phone(user?.phone)}</div>
          </div>
        </div>
        <div className="mt-1 grid grid-cols-3 gap-1">
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center justify-center rounded-lg py-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Тема"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <a
            href={user?.telegram_link}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "flex items-center justify-center rounded-lg py-2 hover:bg-slate-100 dark:hover:bg-slate-800",
              user?.telegram_id ? "text-sky-500" : "text-slate-500",
            )}
            title={user?.telegram_id ? "Telegram привязан" : "Связать Telegram"}
          >
            <Send className="h-4 w-4" />
          </a>
          <button
            onClick={logout}
            className="flex items-center justify-center rounded-lg py-2 text-slate-500 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/10"
            title="Выйти"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200/70 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80 lg:block">
        {sidebar}
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-slate-950/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-pop dark:bg-slate-900">
            <button className="absolute right-3 top-4 rounded-lg p-2 text-slate-500" onClick={() => setOpen(false)}>
              <X className="h-5 w-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200/70 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80 lg:hidden">
        <button onClick={() => setOpen(true)} className="-ml-1 rounded-lg p-2 text-slate-600 dark:text-slate-300">
          <Menu className="h-5 w-5" />
        </button>
        <span className="text-sm font-semibold">Ser Mebel</span>
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
                isActive ? "text-brand-600 dark:text-brand-400" : "text-slate-500",
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
          className="mb-1 flex w-full items-center justify-between px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400"
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
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-200"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
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

