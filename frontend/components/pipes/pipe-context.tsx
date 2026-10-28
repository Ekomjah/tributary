"use client";

import { createContext, useContext } from "react";

import type { PipeStep } from "@/lib/types";

export interface PipeGraphActions {
  updateStep: (nodeId: string, step: PipeStep) => void;
}

const PipeGraphContext = createContext<PipeGraphActions | null>(null);

export const PipeGraphProvider = PipeGraphContext.Provider;

export function usePipeGraph(): PipeGraphActions {
  const actions = useContext(PipeGraphContext);
  if (!actions) {
    throw new Error("usePipeGraph must be used inside a pipe editor");
  }
  return actions;
}
