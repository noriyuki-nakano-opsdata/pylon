import { Wrench } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";

export function FeatureUnavailable({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="p-6">
      <EmptyState
        icon={Wrench}
        title={title}
        description={description}
      />
    </div>
  );
}
