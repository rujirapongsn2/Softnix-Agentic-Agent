import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ToolResultCard({
  name,
  ok,
  output,
  error
}: {
  name: string;
  ok: boolean;
  output?: string;
  error?: string | null;
}) {
  return (
    <Card className="border-border/80">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">Tool: {name}</CardTitle>
        <Badge variant={ok ? "default" : "danger"}>{ok ? "OK" : "ERROR"}</Badge>
      </CardHeader>
      <CardContent>
        {output ? <pre className="max-h-36 overflow-auto text-xs">{output}</pre> : null}
        {error ? <div className="mt-2 text-xs text-red-600">{error}</div> : null}
      </CardContent>
    </Card>
  );
}
