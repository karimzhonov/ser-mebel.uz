import { ArrowLeft, Home, SearchX } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui";

/** Any panel URL that matches no page. */
export default function NotFoundPage() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <div className="mb-5 rounded-3xl bg-brand-50 p-5 text-brand-500 dark:bg-brand-500/10 dark:text-brand-300">
        <SearchX className="h-12 w-12" />
      </div>
      <p className="text-6xl font-bold tracking-tight text-slate-300 dark:text-slate-700">404</p>
      <h1 className="mt-2 text-xl font-semibold">Sahifa topilmadi</h1>
      <p className="muted mt-2 max-w-md text-sm">
        Bunday sahifa yo'q yoki u ko'chirilgan. Manzilni tekshiring yoki bosh sahifaga qayting.
      </p>
      <code className="mt-3 max-w-full truncate rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
        {pathname}
      </code>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button variant="outline" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate(-1)}>
          Orqaga
        </Button>
        <Button icon={<Home className="h-4 w-4" />} onClick={() => navigate("/")}>
          Bosh sahifa
        </Button>
      </div>
    </div>
  );
}
