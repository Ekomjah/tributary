"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

import PipeEditor from "./pipe-editor";

export default function PipeEditorRoute() {
  const params = useParams<{ id: string }>();
  const pipeId = Number(params.id);

  if (!Number.isInteger(pipeId) || pipeId <= 0) {
    return (
      <div className="mx-auto mt-16 max-w-md border border-line bg-sidebar px-6 py-8 text-center">
        <TriangleAlert
          className="mx-auto size-7 text-warn"
          aria-hidden="true"
        />
        <h1 className="mt-3 text-[15px] font-bold">Pipe not found</h1>
        <p className="mt-1 text-[13px] leading-5 text-muted">
          The address does not point at a saved pipe.
        </p>
        <Button
          render={<Link href="/pipes" />}
          variant="secondary"
          size="sm"
          className="mt-4"
        >
          Back to pipes
        </Button>
      </div>
    );
  }

  return <PipeEditor pipeId={pipeId} />;
}
