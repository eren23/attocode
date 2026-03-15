import { RegisterForm } from "@/components/auth/RegisterForm";
import { Code2 } from "lucide-react";

export function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-background to-primary/5">
      <div className="w-full max-w-sm space-y-6 rounded-2xl border border-border bg-card p-10 shadow-xl shadow-black/30 ring-1 ring-white/[0.04]">
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
            <Code2 className="h-7 w-7 text-primary" />
          </div>
          <h1 className="text-2xl font-bold">Create an account</h1>
          <p className="text-sm text-muted-foreground">
            Get started with Attocode
          </p>
        </div>
        <RegisterForm />
      </div>
    </div>
  );
}
