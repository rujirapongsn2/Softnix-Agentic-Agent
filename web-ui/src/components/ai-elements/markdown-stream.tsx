import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownStream({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none text-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
