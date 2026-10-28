import { Suspense } from "react";

import PipeEditorRoute from "@/components/pipes/pipe-editor-route";
import PipesLoading from "@/components/pipes/pipes-loading";

export default function PipePage() {
  return (
    <Suspense fallback={<PipesLoading />}>
      <PipeEditorRoute />
    </Suspense>
  );
}
