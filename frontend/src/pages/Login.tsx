import { useState, type FormEvent } from "react";
import { Lock, Phone } from "lucide-react";
import { errorMessage } from "@/api/client";
import logoWide from "@/assets/logo-wide.png";
import { useAuth } from "@/auth/AuthContext";
import { Button, Field, Input } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const [phone, setPhone] = useState("+998");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(phone.replace(/[\s-]/g, ""), password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Brand panel — the logo's own teal, so the PNG blends in seamlessly. */}
      <div className="relative flex items-center justify-center overflow-hidden bg-brand-900 px-8 py-10 lg:w-1/2 lg:py-0">
        <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-accent-200/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -right-20 h-96 w-96 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="relative text-center">
          <img src={logoWide} alt="SerMebel" className="mx-auto w-64 max-w-full sm:w-80 lg:w-[420px]" />
          <p className="mt-6 hidden text-sm tracking-wide text-accent-200/70 lg:block">
            Мебель на заказ · система управления производством
          </p>
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">Вход в панель</h1>
            <p className="muted mt-1 text-sm">Используйте телефон и пароль сотрудника</p>
          </div>
          <Field label="Телефон">
            <div className="relative">
              <Phone className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input className="pl-9" inputMode="tel" autoComplete="username" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
          </Field>
          <Field label="Пароль">
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input className="pl-9" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </Field>
          {error && (
            <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">{error}</p>
          )}
          <Button type="submit" size="lg" className="w-full" loading={loading}>
            Войти
          </Button>
        </form>
      </div>
    </div>
  );
}
