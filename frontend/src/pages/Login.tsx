import { useState, type FormEvent } from "react";
import { Lock, Phone, Wrench } from "lucide-react";
import { errorMessage } from "@/api/client";
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[480px] -translate-x-1/2 rounded-full bg-brand-400/30 blur-3xl dark:bg-brand-700/20" />
      <form onSubmit={submit} className="card relative w-full max-w-sm space-y-5 p-7">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-600/30">
            <Wrench className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Ser Mebel</h1>
            <p className="muted text-sm">Войдите в панель управления</p>
          </div>
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
        {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={loading}>
          Войти
        </Button>
        <p className="muted text-center text-xs">
          Внутри Telegram вход выполняется автоматически, если профиль привязан к боту.
        </p>
      </form>
    </div>
  );
}
