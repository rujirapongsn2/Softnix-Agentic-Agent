import { motion } from "framer-motion";

export function ThinkingBlock({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-xl border border-dashed border-border bg-secondary/50 p-3 text-xs text-muted-foreground"
    >
      <span className="font-semibold text-foreground">Thinking:</span> {text}
    </motion.div>
  );
}
