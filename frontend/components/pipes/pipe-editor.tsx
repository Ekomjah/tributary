"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  addEdge,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import {
  ArrowLeft,
  History,
  Loader2,
  Play,
  Rss,
  Save,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import {
  defaultStep,
  graphToSteps,
  stepsToGraph,
  type BoxEdge,
  type BoxNode,
  type BoxType,
} from "@/lib/pipes";
import type { BoxRun, Pipe, PipeRun, PipeSpec } from "@/lib/types";
import { cn } from "@/lib/utils";

import BoxPalette from "./box-palette";
import PipeCanvas from "./pipe-canvas";
import { PipeGraphProvider } from "./pipe-context";
import RunHistory from "./run-history";
import RunPanel from "./run-panel";

interface Banner {
  message: string;
  error?: boolean;
}

interface SavedPipe {
  pipe: Pipe;
  nodeIds: string[];
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function tailOf(nodes: BoxNode[], edges: BoxEdge[]): BoxNode | null {
  const sources = new Set(edges.map((edge) => edge.source));
  const tails = nodes.filter((node) => !sources.has(node.id));
  return tails.length === 1 ? tails[0] : null;
}

function isSource(type: BoxType): boolean {
  return type === "fetch" || type === "search";
}

function newNode(type: BoxType, position: { x: number; y: number }): BoxNode {
  return {
    id: `box-${crypto.randomUUID()}`,
    type: "box",
    position,
    data: { step: defaultStep(type) },
    style: { width: 200 },
  };
}

export default function PipeEditor({ pipeId }: { pipeId?: number }) {
  const router = useRouter();

  const initialGraph = useMemo(
    () =>
      pipeId === undefined
        ? stepsToGraph([defaultStep("fetch")])
        : { nodes: [] as BoxNode[], edges: [] as BoxEdge[] },
    [pipeId],
  );

  const [name, setName] = useState("Untitled pipe");
  const [nodes, setNodes, onNodesChange] = useNodesState<BoxNode>(
    initialGraph.nodes,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState<BoxEdge>(
    initialGraph.edges,
  );
  const [savedId, setSavedId] = useState<number | undefined>(pipeId);
  const [dirty, setDirty] = useState(pipeId === undefined);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PipeRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [addingToReader, setAddingToReader] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const activeId = pipeId ?? savedId;
  const loadedId = useRef<number | null>(null);
  const runToken = useRef(0);

  useEffect(() => {
    return () => {
      // Invalidate any in-flight poll when the editor unmounts.
      runToken.current += 1;
    };
  }, []);

  const pipeQuery = useQuery({
    queryKey: ["pipe", pipeId],
    queryFn: ({ signal }) => api.getPipe(pipeId as number, signal),
    enabled: pipeId !== undefined,
  });

  useEffect(() => {
    const pipe = pipeQuery.data;
    if (!pipe || loadedId.current === pipe.id) {
      return;
    }
    loadedId.current = pipe.id;
    setName(pipe.name);
    const graph = stepsToGraph(pipe.spec_json.steps);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setDirty(false);
    setBanner(null);
  }, [pipeQuery.data, setEdges, setNodes]);

  useEffect(() => {
    if (!dirty) {
      return;
    }
    setNodes((current) => {
      if (!current.some((node) => node.data.run)) {
        return current;
      }
      return current.map((node) =>
        node.data.run
          ? { ...node, data: { ...node.data, run: undefined } }
          : node,
      );
    });
  }, [dirty, setNodes]);

  useEffect(() => {
    if (!dirty) {
      return;
    }
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const markDirty = useCallback(() => {
    setDirty(true);
    // A result from the previous spec is stale as soon as the graph changes.
    setResult(null);
    setRunError(null);
  }, []);

  const updateStep = useCallback(
    (nodeId: string, step: BoxNode["data"]["step"]) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, step } }
            : node,
        ),
      );
      markDirty();
    },
    [markDirty, setNodes],
  );

  const actions = useMemo(() => ({ updateStep }), [updateStep]);

  const addNode = useCallback(
    (type: BoxType, position?: { x: number; y: number }) => {
      const rightmost = nodes.reduce(
        (max, node) => Math.max(max, node.position.x),
        0,
      );
      const node = newNode(
        type,
        position ?? {
          x: nodes.length === 0 ? 60 : rightmost + 260,
          y: 140,
        },
      );
      const tail = tailOf(nodes, edges);

      setNodes((current) => [...current, node]);

      if (tail && !isSource(type)) {
        setEdges((currentEdges) =>
          addEdge(
            {
              id: `edge-${tail.id}-${node.id}`,
              source: tail.id,
              target: node.id,
              type: "smoothstep",
              style: { strokeWidth: 1.5 },
            },
            currentEdges,
          ),
        );
      }

      markDirty();
      setBanner(null);
    },
    [edges, markDirty, nodes, setEdges, setNodes],
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange<BoxNode>[]) => {
      onNodesChange(changes);
      if (changes.some((change) => change.type === "remove")) {
        markDirty();
      }
    },
    [markDirty, onNodesChange],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<BoxEdge>[]) => {
      onEdgesChange(changes);
      if (changes.some((change) => change.type === "remove")) {
        markDirty();
      }
    },
    [markDirty, onEdgesChange],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) =>
        addEdge(
          {
            ...connection,
            type: "smoothstep",
            style: { strokeWidth: 1.5 },
          },
          current,
        ),
      );
      markDirty();
      setBanner(null);
    },
    [markDirty, setEdges],
  );

  const save = useCallback(async (): Promise<SavedPipe | null> => {
    const trimmed = name.trim();
    if (!trimmed) {
      setBanner({ message: "Give the pipe a name first.", error: true });
      return null;
    }

    const graph = graphToSteps(nodes, edges);
    if (!graph.ok) {
      setBanner({ message: graph.message, error: true });
      if (graph.nodeId) {
        setNodes((current) =>
          current.map((node) => ({
            ...node,
            selected: node.id === graph.nodeId,
          })),
        );
      }
      return null;
    }

    const spec: PipeSpec = { name: trimmed, steps: graph.steps };
    setSaving(true);
    try {
      let pipe: Pipe;
      if (activeId !== undefined) {
        pipe = await api.updatePipe(activeId, {
          name: trimmed,
          spec_json: spec,
        });
      } else {
        pipe = await api.createPipe(trimmed, spec);
        setSavedId(pipe.id);
        window.history.replaceState(null, "", `/pipes/${pipe.id}`);
      }
      setDirty(false);
      setBanner({ message: `Saved “${pipe.name}”.` });
      return { pipe, nodeIds: graph.nodeIds };
    } catch (error) {
      setBanner({ message: messageOf(error), error: true });
      return null;
    } finally {
      setSaving(false);
    }
  }, [activeId, edges, name, nodes, setNodes]);

  const handleSave = useCallback(() => {
    void save();
  }, [save]);

  const pollRun = useCallback(
    async (runId: number, token: number): Promise<PipeRun | null> => {
      let results = await api.getPipeRun(runId);
      while (results.run.status === "running") {
        await sleep(1000);
        if (runToken.current !== token) {
          return null;
        }
        results = await api.getPipeRun(runId);
      }
      return results;
    },
    [],
  );

  const applyRunToNodes = useCallback(
    (nodeIds: string[], steps: BoxRun[]) => {
      const byId = new Map(nodeIds.map((id, index) => [id, steps[index]]));
      setNodes((current) =>
        current.map((node) => {
          const step = byId.get(node.id);
          if (!step) {
            return node.data.run
              ? { ...node, data: { ...node.data, run: undefined } }
              : node;
          }
          return {
            ...node,
            data: {
              ...node.data,
              run: {
                status:
                  step.status === "error"
                    ? ("error" as const)
                    : step.seconds > 2
                      ? ("slow" as const)
                      : ("done" as const),
                seconds: step.seconds,
                itemsOut: step.items_out,
              },
            },
          };
        }),
      );
    },
    [setNodes],
  );

  const handleRun = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    setResult(null);
    const token = runToken.current + 1;
    runToken.current = token;
    try {
      const saved = await save();
      if (!saved) {
        return;
      }

      setNodes((current) =>
        current.map((node) => ({
          ...node,
          data: { ...node.data, run: { status: "running" as const } },
        })),
      );

      const started = await api.startPipeRun(saved.pipe.id);
      const run = await pollRun(started.id, token);
      if (run === null) {
        return;
      }

      setResult(run);
      setRunError(
        run.run.status === "error"
          ? (run.run.error ?? "That run failed.")
          : null,
      );
      if (run.run.status === "success") {
        setBanner({ message: `Ran “${saved.pipe.name}”.` });
      }

      applyRunToNodes(saved.nodeIds, run.steps);
    } catch (error) {
      if (runToken.current !== token) {
        return;
      }
      setRunError(messageOf(error));
      setNodes((current) =>
        current.map((node) =>
          node.data.run
            ? { ...node, data: { ...node.data, run: undefined } }
            : node,
        ),
      );
    } finally {
      if (runToken.current === token) {
        setRunning(false);
      }
    }
  }, [applyRunToNodes, pollRun, save, setNodes]);

  const handleAddToReader = useCallback(async () => {
    if (addingToReader) {
      return;
    }

    setAddingToReader(true);
    try {
      const saved = await save();
      if (!saved) {
        return;
      }

      const added = await api.addPipeFeed(saved.pipe.id);
      let count = added.items;
      let verb = "Added";
      if (!added.created) {
        const refreshed = await api.refreshFeed(added.feed.id);
        if (refreshed.error) {
          setBanner({
            message: `“${added.feed.title}” is in the reader, but the refresh failed: ${refreshed.error}`,
            error: true,
          });
          return;
        }
        count = refreshed.new_items;
        verb = "Updated";
      }

      setBanner({
        message: `${verb} “${added.feed.title}” in the reader: ${count} item${
          count === 1 ? "" : "s"
        }.`,
      });
    } catch (error) {
      setBanner({ message: messageOf(error), error: true });
    } finally {
      setAddingToReader(false);
    }
  }, [addingToReader, save]);

  const openHistoryRun = useCallback(
    (run: PipeRun) => {
      if (run.run.status !== "running") {
        setResult(run);
        setRunError(
          run.run.status === "error"
            ? (run.run.error ?? "That run failed.")
            : null,
        );
        return;
      }

      const token = runToken.current + 1;
      runToken.current = token;
      setRunning(true);
      setRunError(null);
      setResult(null);
      void (async () => {
        try {
          const finished = await pollRun(run.run.id, token);
          if (finished === null) {
            return;
          }
          setResult(finished);
          setRunError(
            finished.run.status === "error"
              ? (finished.run.error ?? "That run failed.")
              : null,
          );
        } catch (error) {
          if (runToken.current === token) {
            setRunError(messageOf(error));
          }
        } finally {
          if (runToken.current === token) {
            setRunning(false);
          }
        }
      })();
    },
    [pollRun],
  );

  const handleCloseRun = useCallback(() => {
    // Detach from a run that is still going; history can reopen it.
    runToken.current += 1;
    setResult(null);
    setRunError(null);
    setRunning(false);
    setNodes((current) =>
      current.map((node) =>
        node.data.run
          ? { ...node, data: { ...node.data, run: undefined } }
          : node,
      ),
    );
  }, [setNodes]);

  const handleDelete = useCallback(async () => {
    if (activeId === undefined) {
      return;
    }
    if (!window.confirm("Delete this pipe? This cannot be undone.")) {
      return;
    }

    setDeleting(true);
    try {
      await api.deletePipe(activeId);
      router.push("/pipes");
    } catch (error) {
      setBanner({ message: messageOf(error), error: true });
      setDeleting(false);
    }
  }, [activeId, router]);

  const busy = saving || running || deleting || addingToReader;
  const visibleBanner: Banner | null =
    banner ??
    (pipeQuery.error
      ? { message: messageOf(pipeQuery.error), error: true }
      : null);

  if (pipeQuery.isLoading) {
    return (
      <div className="grid h-full place-items-center text-[13px] text-muted">
        <span className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading pipe…
        </span>
      </div>
    );
  }

  if (pipeQuery.error instanceof ApiError && pipeQuery.error.status === 404) {
    return (
      <div className="mx-auto mt-16 max-w-md border border-line bg-sidebar px-6 py-8 text-center">
        <TriangleAlert
          className="mx-auto size-7 text-warn"
          aria-hidden="true"
        />
        <h1 className="mt-3 text-[15px] font-bold">Pipe not found</h1>
        <p className="mt-1 text-[13px] leading-5 text-muted">
          It may have been deleted from this machine.
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

  return (
    <PipeGraphProvider value={actions}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-divider bg-canvas px-3">
          <Button
            type="button"
            variant="icon"
            size="icon-sm"
            onClick={() => router.push("/pipes")}
            aria-label="Back to pipes"
            title="Back to pipes"
          >
            <ArrowLeft className="size-4" />
          </Button>

          <input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              markDirty();
            }}
            placeholder="Untitled pipe"
            aria-label="Pipe name"
            spellCheck={false}
            className="h-8 min-w-0 flex-1 rounded-sm border border-transparent bg-transparent px-2 text-[15px] font-bold outline-none hover:border-line focus:border-accent"
          />

          {dirty && (
            <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.06em] text-warn">
              Unsaved
            </span>
          )}

          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {activeId !== undefined && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void handleDelete()}
                disabled={busy}
                className="text-danger hover:text-danger-dark max-[700px]:hidden"
              >
                <Trash2 className="size-3.5" />
                Delete
              </Button>
            )}
            {activeId !== undefined && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setHistoryOpen(true)}
                disabled={busy}
                title="Run history"
                className="gap-1.5"
              >
                <History className="size-3.5" />
                <span className="max-[900px]:hidden">History</span>
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void handleAddToReader()}
              disabled={busy}
              title="Add this pipe to the reader"
              className="gap-1.5"
            >
              {addingToReader ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Rss className="size-3.5" />
              )}
              <span className="max-[900px]:hidden">
                {addingToReader ? "Adding…" : "Add to reader"}
              </span>
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleSave}
              disabled={busy}
            >
              <Save className="size-3.5" />
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => void handleRun()}
              disabled={busy}
            >
              {running ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Play className="size-3.5" />
              )}
              {running ? "Running…" : "Run"}
            </Button>
          </div>
        </div>

        {visibleBanner && (
          <div
            role={visibleBanner.error ? "alert" : "status"}
            aria-live={visibleBanner.error ? "assertive" : "polite"}
            className={cn(
              "flex shrink-0 items-start gap-2 border-b border-divider px-4 py-1.5 text-[12px] leading-5",
              visibleBanner.error ? "text-danger" : "text-muted",
            )}
          >
            {visibleBanner.error && (
              <TriangleAlert
                className="mt-0.5 size-3.5 shrink-0"
                aria-hidden="true"
              />
            )}
            <span className="min-w-0 flex-1">{visibleBanner.message}</span>
            <Button
              type="button"
              variant="icon"
              size="icon-xs"
              className="-mr-1 -mt-0.5 text-faint hover:text-ink"
              onClick={() => setBanner(null)}
              aria-label="Dismiss message"
            >
              <X className="size-3.5" />
            </Button>
          </div>
        )}

        <div className="flex min-h-0 flex-1 max-[900px]:flex-col">
          <BoxPalette onAdd={(type) => addNode(type)} />

          <div className="min-h-0 min-w-0 flex-1">
            <ReactFlowProvider>
              <PipeCanvas
                nodes={nodes}
                edges={edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onConnect={handleConnect}
                onAddNode={addNode}
              />
            </ReactFlowProvider>
          </div>

          <RunPanel
            key={result?.run.id ?? "run-panel"}
            result={result}
            error={runError}
            running={running}
            onClose={handleCloseRun}
          />
        </div>

        <RunHistory
          pipeId={activeId ?? null}
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          onOpenRun={openHistoryRun}
        />
      </div>
    </PipeGraphProvider>
  );
}
