"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type DragEvent,
} from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from "@xyflow/react";

import type { BoxEdge, BoxNode, BoxType } from "@/lib/pipes";

import BoxNodeView from "./box-node";

const nodeTypes = { box: BoxNodeView };

interface PipeCanvasProps {
  nodes: BoxNode[];
  edges: BoxEdge[];
  onNodesChange: OnNodesChange<BoxNode>;
  onEdgesChange: OnEdgesChange<BoxEdge>;
  onConnect: OnConnect;
  onAddNode: (type: BoxType, position: { x: number; y: number }) => void;
}

export default function PipeCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onAddNode,
}: PipeCanvasProps) {
  const { fitView, screenToFlowPosition } = useReactFlow();
  const hasFitted = useRef(false);

  // A saved pipe loads after the canvas mounts, so fit it once the boxes land.
  useEffect(() => {
    if (hasFitted.current || nodes.length === 0) {
      return;
    }
    hasFitted.current = true;
    const frame = requestAnimationFrame(() => {
      void fitView({ padding: 0.25 });
    });
    return () => cancelAnimationFrame(frame);
  }, [fitView, nodes.length]);

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      if (!connection.source || !connection.target) {
        return false;
      }
      if (connection.source === connection.target) {
        return false;
      }
      if (
        edges.some(
          (edge) =>
            edge.source === connection.source ||
            edge.target === connection.target,
        )
      ) {
        return false;
      }

      // MVP pipes are a single chain, so refuse wires that close a loop.
      let cursor: string | undefined = connection.target;
      const seen = new Set<string>();
      while (cursor && !seen.has(cursor)) {
        if (cursor === connection.source) {
          return false;
        }
        seen.add(cursor);
        cursor = edges.find((edge) => edge.source === cursor)?.target;
      }

      return true;
    },
    [edges],
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData(
        "application/tributary-box",
      ) as BoxType;
      if (!type) {
        return;
      }
      onAddNode(
        type,
        screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      );
    },
    [onAddNode, screenToFlowPosition],
  );

  const defaultEdgeOptions = useMemo(
    () => ({
      type: "smoothstep",
      style: { strokeWidth: 1.5 },
    }),
    [],
  );

  return (
    <div className="h-full w-full" onDragOver={onDragOver} onDrop={onDrop}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        defaultEdgeOptions={defaultEdgeOptions}
        deleteKeyCode={["Backspace", "Delete"]}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.35}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        className="bg-canvas"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={16}
          size={1}
          color="#ececec"
        />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          pannable
          zoomable
          position="bottom-right"
          className="!border !border-line !bg-sidebar"
          nodeColor="#d9d9d9"
          maskColor="rgba(255,255,255,0.72)"
        />
      </ReactFlow>
    </div>
  );
}
