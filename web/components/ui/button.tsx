"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

/**
 * ChAAMP Button — matches the design system primitives from the handoff:
 *
 *   variants: primary | secondary | ghost | danger | quiet
 *   sizes:    sm 28h  | md 34h    | lg 40h
 *
 * Notes:
 *   - "primary" uses the indigo accent on a white-text foreground. No teal
 *     here; teal is reserved for the gradient.
 *   - "secondary" is a white card surface with the standard slate-200 border.
 *   - "ghost" is transparent until hover (slate-100 bg).
 *   - "danger" uses the critical color on a white card — destructive but
 *     visually quiet (a confirmation modal carries the heavier weight).
 *   - "quiet" is the slate-100 chip-like button used in low-importance rows.
 */
const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-2 select-none",
    "font-ui font-medium rounded-2 transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
  ),
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-white hover:bg-accent-700 shadow-1",
        secondary:
          "bg-card text-ink border border-slate-200 hover:bg-slate-50",
        ghost:
          "bg-transparent text-slate-700 hover:bg-slate-100",
        danger:
          "bg-card text-critical border border-slate-200 hover:bg-critical-soft",
        quiet:
          "bg-slate-100 text-slate-700 hover:bg-slate-200",
      },
      size: {
        sm: "h-7 px-2.5 text-12",
        md: "h-[34px] px-3.5 text-13",
        lg: "h-10 px-4 text-14",
      },
      fullWidth: {
        true: "w-full",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the child element instead of a `<button>` (for use with Next Link, etc.). */
  asChild?: boolean;
  /** Optional icon rendered to the left of the label. */
  iconLeft?: React.ReactNode;
  /** Optional icon rendered to the right of the label. */
  iconRight?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, fullWidth, asChild = false, iconLeft, iconRight, children, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size, fullWidth }), className)}
        {...props}
      >
        {iconLeft}
        {children}
        {iconRight}
      </Comp>
    );
  },
);
Button.displayName = "Button";

/**
 * Square icon-only button. Used heavily in the topbar (history, menu) and
 * in expansion controls inside chat messages.
 */
export const IconButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    "aria-label": string; // required for accessibility
    active?: boolean;
    size?: number;
  }
>(({ className, active, size = 32, ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center rounded-2 transition-colors",
      "text-slate-700",
      active
        ? "bg-accent-soft text-accent-700"
        : "hover:bg-slate-100",
      "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
      "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent",
      className,
    )}
    style={{ width: size, height: size }}
    {...props}
  />
));
IconButton.displayName = "IconButton";
