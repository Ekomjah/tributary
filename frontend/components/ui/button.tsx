import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-sm border border-transparent text-[13px] leading-none transition-colors duration-100 disabled:pointer-events-none disabled:text-faint disabled:opacity-70 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "border-danger-dark bg-danger px-4 text-[11px] font-bold uppercase tracking-[0.04em] text-white hover:bg-danger-dark active:shadow-[inset_0_1px_2px_rgba(0,0,0,0.2)]",
        secondary:
          "border-line bg-chrome px-3 text-ink hover:bg-[#e8e8e8] active:shadow-[inset_0_1px_1px_rgba(0,0,0,0.12)]",
        outline:
          "border-line bg-canvas px-3 text-ink hover:bg-chrome active:shadow-[inset_0_1px_1px_rgba(0,0,0,0.12)]",
        ghost:
          "border-transparent bg-transparent px-2 text-muted hover:bg-[#f0f0f0] hover:text-ink",
        link: "border-transparent bg-transparent p-0 text-accent hover:text-accent-dark hover:underline hover:underline-offset-2",
        icon:
          "border-transparent bg-transparent p-0 text-muted hover:bg-[#f0f0f0] hover:text-ink",
        "icon-bordered":
          "border-line bg-chrome p-0 text-ink hover:bg-[#e8e8e8]",
      },
      size: {
        default: "h-8",
        sm: "h-7 px-2.5 text-[12px]",
        xs: "h-6 px-2 text-[11px]",
        icon: "size-8 p-0",
        "icon-sm": "size-7 p-0 [&_svg]:size-3.5",
        "icon-xs": "size-6 p-0 [&_svg]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "default",
    },
  },
);

type ButtonProps = ButtonPrimitive.Props &
  VariantProps<typeof buttonVariants>;

function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
