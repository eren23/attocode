import { useMe, useLogout } from "@/api/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { LogOut, User } from "lucide-react";

export function Topbar() {
  const { data: user } = useMe();
  const logout = useLogout();

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-zinc-950 px-6">
      <div />
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-2 text-sm">
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={user.name}
                className="h-7 w-7 rounded-full"
              />
            ) : (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 text-primary">
                <User className="h-4 w-4" />
              </div>
            )}
            <span className="text-muted-foreground">{user.name}</span>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => logout.mutate()}
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
