import { Loader2 } from "lucide-react";

export default function PipesLoading() {
  return (
    <div className="grid h-full place-items-center text-[13px] text-muted">
      <span className="flex items-center gap-2">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Loading pipe…
      </span>
    </div>
  );
}
