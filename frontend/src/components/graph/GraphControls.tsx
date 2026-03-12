import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Network } from "lucide-react";

interface GraphControlsProps {
  file: string;
  depth: number;
  onFileChange: (file: string) => void;
  onDepthChange: (depth: number) => void;
  onGenerate: () => void;
  loading: boolean;
}

export function GraphControls({
  file,
  depth,
  onFileChange,
  onDepthChange,
  onGenerate,
  loading,
}: GraphControlsProps) {
  return (
    <div className="flex items-end gap-3">
      <div className="flex-1 space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          Start File (optional)
        </label>
        <Input
          placeholder="e.g. src/main.ts"
          value={file}
          onChange={(e) => onFileChange(e.target.value)}
        />
      </div>
      <div className="w-24 space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          Depth
        </label>
        <Input
          type="number"
          min={1}
          max={10}
          value={depth}
          onChange={(e) => onDepthChange(Number(e.target.value))}
        />
      </div>
      <Button onClick={onGenerate} disabled={loading}>
        <Network className="h-4 w-4" />
        {loading ? "Generating..." : "Generate"}
      </Button>
    </div>
  );
}
