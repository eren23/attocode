import { RegisterForm } from "@/components/auth/RegisterForm";
import { Code2 } from "lucide-react";

export function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-8">
        <div className="flex flex-col items-center gap-2">
          <Code2 className="h-8 w-8 text-primary" />
          <h1 className="text-xl font-semibold">Create an account</h1>
          <p className="text-sm text-muted-foreground">
            Get started with Attocode
          </p>
        </div>
        <RegisterForm />
      </div>
    </div>
  );
}
