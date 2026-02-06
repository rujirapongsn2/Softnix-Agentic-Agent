import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function MessageBubble({
  role,
  children,
  timestamp
}: {
  role: "user" | "assistant" | "system";
  children: ReactNode;
  timestamp?: string;
}) {
  const isUser = role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn("w-full", isUser ? "flex justify-end" : "flex justify-start")}
    >
      <div
        className={cn(
          "max-w-[82%] rounded-2xl px-4 py-3 shadow-sm",
          isUser ? "bg-primary text-primary-foreground" : "bg-white border border-border"
        )}
      >
        <div className="mb-1 text-[11px] opacity-70">{role.toUpperCase()}</div>
        <div className="text-sm leading-6">{children}</div>
        {timestamp ? <div className="mt-2 text-[10px] opacity-70">{timestamp}</div> : null}
      </div>
    </motion.div>
  );
}
