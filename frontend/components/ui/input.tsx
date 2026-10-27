import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";

import { cn } from "@/lib/utils";

const inputClasses =
  "h-8 w-full rounded-sm border border-line bg-canvas px-2 text-[13px] text-ink placeholder:text-faint focus-visible:border-accent focus-visible:shadow-[inset_0_0_0_1px_var(--blue)] focus-visible:outline-none disabled:bg-chrome disabled:text-faint";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(inputClasses, className)}
      {...props}
    />
  );
}

export { Input, inputClasses };
