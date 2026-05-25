import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Standard Tailwind classname combiner with tailwind-merge's conflict resolution. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
