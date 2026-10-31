"use client";

import { useState, useEffect, useCallback, useRef } from "react";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" && window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "http://localhost:8000");

// ─── Types ────────────────────────────────────────────────────────────────────

interface UploadedDoc {
  filename: string;
  saved_filename: string;
  file_size_bytes: number;
}

interface Citation {
  citation_id: number;
  filename: string;
  document_title?: string;
  effective_or_issue_date?: string;
  quoted_snippet?: string;
}

interface ConflictItem {
  issue_type?: string;
  description?: string;
  evidence?: string;
  severity?: string;
}

interface AskResult {
  outcome: "RESOLVED" | "CONFLICT" | "ABSTAIN";
  final_answer: string;
  explanation: string;
  citations: Citation[];
  conflicting_evidence: ConflictItem[];
  abstention_reason?: string;
  resolution_basis?: string;
  critic_status: string;
  critic_issues_count: number;
}

interface GraphNode {
  id: string;
  filename?: string;
  original_filename?: string;
  saved_filename?: string;
  title?: string;
  document_title?: string;
  effective_date?: string;
  issue_date?: string;
  publication_or_issue_date?: string;
  version?: string;
  version_number?: string;
  document_identifier?: string;
  policy_or_document_identifier?: string;
  scope?: string;
  geographic_or_organizational_scope?: string;
  amendment_status?: boolean;
  appears_amendment_or_replacement?: boolean;
  parent_policy_identifier?: string;
  referenced_parent_or_previous_policy_identifier?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  relationship: "SUPERSEDES" | "AMENDS" | "SAME_POLICY" | "RELATED_TO" | string;
  type?: string;
  source_identifier?: string;
  target_identifier?: string;
  evidence?: string;
}

// ─── Compare Types ────────────────────────────────────────────────────────────

interface DocMetadata {
  document_title?: string;
  version?: string;
  issue_date?: string;
  effective_date?: string;
  scope?: string;
  policy_or_document_identifier?: string;
}

interface DocumentCompareSide {
  filename: string;
  saved_filename?: string;
  is_empty: boolean;
  metadata: DocMetadata;
  passages: string[];
}

interface ComparisonDifference {
  category: string;
  doc_a_value: string;
  doc_b_value: string;
  description: string;
  is_conflicting: boolean;
}

interface CompareCitation {
  citation_id: number;
  filename: string;
  saved_filename?: string;
  title?: string;
  date?: string;
  snippet: string;
}

interface CompareResult {
  status: string;
  outcome: "RESOLVED" | "CONFLICT" | "ABSTAIN";
  relationship?: "SUPERSEDES" | "AMENDS" | "SAME_POLICY" | "RELATED_TO" | string | null;
  relationship_direction?: string | null;
  relationship_evidence?: string | null;
  document_a: DocumentCompareSide;
  document_b: DocumentCompareSide;
  differences: ComparisonDifference[];
  differences_count: number;
  conflict?: {
    conflict_type?: string;
    short_explanation?: string;
    explanation?: string;
    appears_resolvable?: boolean;
    resolvability_reason?: string;
    evidence_snippets?: Array<{ filename: string; snippet: string }>;
  } | null;
  explanation: string;
  citations: CompareCitation[];
}

const RELATIONSHIP_CONFIG: Record<
  string,
  {
    color: string;
    label: string;
    badgeBg: string;
    badgeText: string;
    border: string;
    dash: string;
    strokeWidth: number;
    description: string;
  }
> = {
  SUPERSEDES: {
    color: "#ef4444",
    label: "SUPERSEDES",
    badgeBg: "bg-rose-50",
    badgeText: "text-rose-700",
    border: "border-rose-300",
    dash: "none",
    strokeWidth: 2.5,
    description: "Explicitly replaces or overrides a prior policy",
  },
  AMENDS: {
    color: "#f59e0b",
    label: "AMENDS",
    badgeBg: "bg-amber-50",
    badgeText: "text-amber-700",
    border: "border-amber-300",
    dash: "6 4",
    strokeWidth: 2.5,
    description: "Modifies or updates specific rules of a parent policy",
  },
  SAME_POLICY: {
    color: "#10b981",
    label: "SAME_POLICY",
    badgeBg: "bg-emerald-50",
    badgeText: "text-emerald-700",
    border: "border-emerald-300",
    dash: "3 3",
    strokeWidth: 2.5,
    description: "Shares the same policy identifier across versions",
  },
  RELATED_TO: {
    color: "#6366f1",
    label: "RELATED_TO",
    badgeBg: "bg-indigo-50",
    badgeText: "text-indigo-700",
    border: "border-indigo-300",
    dash: "8 4",
    strokeWidth: 2,
    description: "Cross-references or contextual provenance relationship",
  },
};

function computeGraphLayout(nodes: GraphNode[], edges: GraphEdge[], width = 860, height = 480) {
  const pos: Record<string, { x: number; y: number }> = {};
  const N = nodes.length;
  if (N === 0) return pos;

  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width * 0.36, height * 0.36, 150 + N * 8);

  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / N - Math.PI / 2;
    pos[n.id] = {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  for (let iter = 0; iter < 50; iter++) {
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const id1 = nodes[i].id;
        const id2 = nodes[j].id;
        const p1 = pos[id1];
        const p2 = pos[id2];
        if (!p1 || !p2) continue;
        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 160) {
          const force = ((160 - dist) / dist) * 0.14;
          p1.x -= dx * force;
          p1.y -= dy * force;
          p2.x += dx * force;
          p2.y += dy * force;
        }
      }
    }

    edges.forEach((e) => {
      const p1 = pos[e.source];
      const p2 = pos[e.target];
      if (p1 && p2) {
        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = 130;
        const force = (dist - targetDist) * 0.05;
        p1.x += (dx / dist) * force;
        p1.y += (dy / dist) * force;
        p2.x -= (dx / dist) * force;
        p2.y -= (dy / dist) * force;
      }
    });

    nodes.forEach((n) => {
      const p = pos[n.id];
      if (p) {
        p.x = Math.max(65, Math.min(width - 65, p.x));
        p.y = Math.max(45, Math.min(height - 45, p.y));
      }
    });
  }

  return pos;
}

// ─── Small UI Components ──────────────────────────────────────────────────────

function Spinner({ size = "h-4 w-4" }: { size?: string }) {
  return (
    <svg className={`animate-spin ${size} text-current`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cfg: Record<string, { bg: string; text: string; border: string; icon: string; label: string }> = {
    RESOLVED: {
      bg: "bg-emerald-50",
      text: "text-emerald-800",
      border: "border-emerald-300",
      icon: "✓",
      label: "RESOLVED",
    },
    CONFLICT: {
      bg: "bg-amber-50",
      text: "text-amber-800",
      border: "border-amber-300",
      icon: "⚡",
      label: "CONFLICT",
    },
    ABSTAIN: {
      bg: "bg-slate-100",
      text: "text-slate-700",
      border: "border-slate-300",
      icon: "–",
      label: "ABSTAIN",
    },
  };
  const c = cfg[outcome] ?? cfg.ABSTAIN;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border ${c.bg} ${c.text} ${c.border}`}>
      <span>{c.icon}</span>
      {c.label}
    </span>
  );
}

function RelationshipBadge({
  relationship,
  direction,
  evidence,
}: {
  relationship?: string | null;
  direction?: string | null;
  evidence?: string | null;
}) {
  if (!relationship) {
    return (
      <div className="inline-flex items-center gap-2 text-xs text-slate-500 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg shadow-2xs">
        <span className="w-2 h-2 rounded-full bg-slate-400" />
        <span className="font-semibold text-slate-700">No Explicit TPCG Link</span>
        <span className="text-[11px] text-slate-400 hidden sm:inline">(Independent / concurrent policies)</span>
      </div>
    );
  }

  const relUpper = relationship.toUpperCase();
  const cfg = RELATIONSHIP_CONFIG[relUpper] || {
    color: "#6366f1",
    label: relUpper,
    badgeBg: "bg-indigo-50",
    badgeText: "text-indigo-700",
    border: "border-indigo-300",
    description: "Relationship",
  };

  return (
    <div className={`inline-flex flex-col sm:flex-row sm:items-center gap-2 px-3.5 py-1.5 rounded-xl border ${cfg.badgeBg} ${cfg.border} shadow-2xs`}>
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: cfg.color }} />
        <span className={`text-xs font-bold tracking-wide ${cfg.badgeText}`}>{cfg.label}</span>
        {direction && (
          <span className="text-[11px] font-semibold text-slate-700 bg-white/90 px-2 py-0.5 rounded border border-slate-200">
            {direction}
          </span>
        )}
      </div>
      {evidence && (
        <span className="text-[11px] text-slate-600 italic sm:border-l sm:border-slate-300 sm:pl-2">
          {evidence}
        </span>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  // ── Navigation Tab ──
  const [activeTab, setActiveTab] = useState<"ask" | "compare">("ask");

  // ── Connection ──
  const [connectionStatus, setConnectionStatus] = useState<"checking" | "connected" | "disconnected">("checking");
  const [isLoadingConnection, setIsLoadingConnection] = useState(true);

  // ── Upload ──
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadFeedback, setUploadFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [uploadedDocs, setUploadedDocs] = useState<UploadedDoc[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // ── Compare ──
  const [compareDocA, setCompareDocA] = useState<string>("");
  const [compareDocB, setCompareDocB] = useState<string>("");
  const [isComparing, setIsComparing] = useState(false);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);

  // ── Graph ──
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null);
  const [isRebuildingGraph, setIsRebuildingGraph] = useState(false);
  const [graphFilter, setGraphFilter] = useState<string>("ALL");
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // ── Ask ──
  const [question, setQuestion] = useState("");
  const [isAsking, setIsAsking] = useState(false);
  const [askResult, setAskResult] = useState<AskResult | null>(null);
  const [askError, setAskError] = useState<string | null>(null);

  // ── Demo Questions ──
  const DEMO_CASES = [
    {
      id: "vande-bharat",
      label: "Vande Bharat entitlement",
      dotColor: "bg-emerald-500",
      question: "Can Central Government employees travel by Vande Bharat Express on official tours, and what travel entitlement applies?",
    },
    {
      id: "conflict-limits",
      label: "Conflicting documents",
      dotColor: "bg-amber-500",
      question: "If two policy documents contain different travel limits, which one should apply?",
    },
    {
      id: "not-enough",
      label: "Not enough evidence",
      dotColor: "bg-slate-400",
      question: "Can you answer a question if the uploaded documents do not contain enough evidence?",
    },
  ];

  // ── Check Connection ──
  const checkConnection = useCallback(async () => {
    setIsLoadingConnection(true);
    setConnectionStatus("checking");
    const candidates = [
      BACKEND_URL,
      "http://localhost:8000",
      "http://127.0.0.1:8000",
    ];
    let connected = false;
    for (const base of candidates) {
      try {
        const resp = await fetch(`${base}/health`, { cache: "no-store" });
        const data = await resp.json().catch(() => null);
        if (resp.ok && data?.status === "healthy") {
          connected = true;
          break;
        }
      } catch {
        // try next candidate
      }
    }
    setConnectionStatus(connected ? "connected" : "disconnected");
    setIsLoadingConnection(false);
  }, []);

  useEffect(() => {
    checkConnection();
  }, [checkConnection]);

  // ── Fetch Graph Data ──
  const fetchGraphData = useCallback(async () => {
    setIsLoadingDocs(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/graph`, { cache: "no-store" });
      if (!resp.ok) return;
      const data = await resp.json();
      const rawNodes: GraphNode[] = data.nodes ?? [];
      const rawEdges: GraphEdge[] = data.edges ?? [];
      setGraphNodes(rawNodes);
      setGraphEdges(rawEdges);
      const docs = rawNodes.map((n) => ({
        filename: n.original_filename || n.filename || n.id || "Unknown",
        saved_filename: n.saved_filename || n.id || "",
        file_size_bytes: 0,
      }));
      setUploadedDocs(docs);
      if (docs.length >= 1) {
        setCompareDocA((prev) => prev || docs[0].saved_filename || docs[0].filename);
      }
      if (docs.length >= 2) {
        setCompareDocB((prev) => prev || docs[1].saved_filename || docs[1].filename);
      }
      setNodePositions((prev) => {
        const allKnown = rawNodes.length > 0 && rawNodes.every((n) => prev[n.id]);
        if (allKnown && rawNodes.length === Object.keys(prev).length) {
          return prev;
        }
        return computeGraphLayout(rawNodes, rawEdges);
      });
    } catch {
      // ignore
    } finally {
      setIsLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  // ── Rebuild Graph ──
  const handleRebuildAndRefreshGraph = async () => {
    setIsRebuildingGraph(true);
    try {
      const rebuildResp = await fetch(`${BACKEND_URL}/graph/rebuild`, { method: "POST" });
      if (rebuildResp.ok) {
        const data = await rebuildResp.json();
        const rawNodes: GraphNode[] = data.nodes ?? [];
        const rawEdges: GraphEdge[] = data.edges ?? [];
        setGraphNodes(rawNodes);
        setGraphEdges(rawEdges);
        const docs = rawNodes.map((n) => ({
          filename: n.original_filename || n.filename || n.id || "Unknown",
          saved_filename: n.saved_filename || n.id || "",
          file_size_bytes: 0,
        }));
        setUploadedDocs(docs);
        if (docs.length >= 1) {
          setCompareDocA((prev) => prev || docs[0].saved_filename || docs[0].filename);
        }
        if (docs.length >= 2) {
          setCompareDocB((prev) => prev || docs[1].saved_filename || docs[1].filename);
        }
        const newPos = computeGraphLayout(rawNodes, rawEdges);
        setNodePositions(newPos);
      } else {
        await fetchGraphData();
      }
    } catch {
      await fetchGraphData();
    } finally {
      setIsRebuildingGraph(false);
    }
  };

  // ── Drag Handlers ──
  const handleNodeMouseDown = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggingNodeId(id);
    setSelectedGraphNodeId(id);
  };

  const handleSvgMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!draggingNodeId || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scaleX = 860 / rect.width;
    const scaleY = 480 / rect.height;
    const x = Math.max(45, Math.min(815, (e.clientX - rect.left) * scaleX));
    const y = Math.max(40, Math.min(440, (e.clientY - rect.top) * scaleY));
    setNodePositions((prev) => ({
      ...prev,
      [draggingNodeId]: { x, y },
    }));
  };

  const handleSvgMouseUp = () => {
    setDraggingNodeId(null);
  };

  // ── Upload ──
  const validateAndSetFile = (file: File) => {
    setUploadFeedback(null);
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext !== "pdf" && ext !== "txt") {
      setUploadFeedback({ type: "error", message: "Only PDF (.pdf) and Text (.txt) files are supported." });
      return;
    }
    setSelectedFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) validateAndSetFile(e.target.files[0]);
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setUploadFeedback(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setIsUploading(true);
    setUploadFeedback(null);
    const formData = new FormData();
    formData.append("file", selectedFile);
    try {
      const resp = await fetch(`${BACKEND_URL}/upload`, { method: "POST", body: formData });
      const data = await resp.json().catch(() => null);
      if (resp.ok && data?.status === "success") {
        setUploadFeedback({
          type: "success",
          message: `"${data.original_filename}" uploaded successfully.`,
        });
        handleRemoveFile();
        await handleRebuildAndRefreshGraph();
      } else {
        setUploadFeedback({ type: "error", message: data?.detail ?? "Upload failed." });
      }
    } catch {
      setUploadFeedback({ type: "error", message: "Could not reach backend at http://localhost:8000." });
    } finally {
      setIsUploading(false);
    }
  };

  // ── Ask ──
  const handleAsk = async (queryToAsk?: string) => {
    const q = (queryToAsk ?? question).trim();
    if (!q) return;
    setIsAsking(true);
    setAskResult(null);
    setAskError(null);
    try {
      const resp = await fetch(`${BACKEND_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, top_k: 5 }),
      });
      const data = await resp.json().catch(() => null);
      if (resp.ok && data?.status === "success") {
        setAskResult(data as AskResult);
      } else {
        setAskError(data?.detail ?? "The backend returned an unexpected error.");
      }
    } catch {
      setAskError("Could not reach backend at http://localhost:8000.");
    } finally {
      setIsAsking(false);
    }
  };

  // ── Compare Actions ──
  const handleCompare = async (overrideA?: string, overrideB?: string) => {
    const fileA = (overrideA !== undefined ? overrideA : compareDocA).trim();
    const fileB = (overrideB !== undefined ? overrideB : compareDocB).trim();

    if (!fileA || !fileB) {
      setCompareError("Please select both Document A and Document B from the dropdowns.");
      return;
    }

    setIsComparing(true);
    setCompareResult(null);
    setCompareError(null);

    try {
      const resp = await fetch(`${BACKEND_URL}/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_a: fileA, file_b: fileB }),
      });
      const data = await resp.json().catch(() => null);
      if (resp.ok && data?.status === "success") {
        setCompareResult(data as CompareResult);
      } else {
        setCompareError(data?.detail ?? "Comparison failed. Please verify that both documents exist.");
      }
    } catch {
      setCompareError("Could not reach backend at " + BACKEND_URL);
    } finally {
      setIsComparing(false);
    }
  };

  const handleSwapCompareDocs = () => {
    const temp = compareDocA;
    setCompareDocA(compareDocB);
    setCompareDocB(temp);
    if (compareResult) {
      handleCompare(compareDocB, temp);
    }
  };

  const handleSampleCompare = (caseType: "supersession" | "scope" | "empty") => {
    const findDoc = (keywords: string[]) => {
      const match = uploadedDocs.find((d) =>
        keywords.some(
          (kw) =>
            d.filename.toLowerCase().includes(kw.toLowerCase()) ||
            d.saved_filename.toLowerCase().includes(kw.toLowerCase())
        )
      );
      return match ? match.saved_filename || match.filename : "";
    };

    let targetA = "";
    let targetB = "";

    if (caseType === "supersession") {
      targetA = findDoc(["2025", "0ffd9648", "sec_policy.txt"]) || "sec_policy.txt";
      targetB = findDoc(["2022", "3222c150", "sec_policy_2022.txt"]) || "sec_policy_2022.txt";
    } else if (caseType === "scope") {
      targetA = findDoc(["8c126522", "global_governance"]) || "global_governance.txt";
      targetB = findDoc(["6605bf30", "apac_governance"]) || "apac_governance.pdf";
    } else if (caseType === "empty") {
      targetA = findDoc(["6c4ab9ba", "blank", "empty"]) || "blank.pdf";
      targetB = findDoc(["3222c150", "sec_policy_2022"]) || "sec_policy_2022.txt";
    }

    if (targetA && targetB) {
      setCompareDocA(targetA);
      setCompareDocB(targetB);
      handleCompare(targetA, targetB);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top_left,_var(--tw-gradient-stops))] from-teal-50/60 via-slate-50 to-orange-50/40 py-8 px-4 sm:px-8 flex justify-center items-start font-sans text-slate-800 antialiased">
      <main className="w-full max-w-6xl bg-white rounded-[32px] shadow-[0_25px_60px_-15px_rgba(0,0,0,0.06)] border border-slate-200/80 p-6 sm:p-10 space-y-7">
        
        {/* ── Top Header ── */}
        <header className="flex items-center justify-between pb-2">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-[#0d4a3e] flex items-center justify-center text-white shadow-2xs">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="font-bold text-slate-900 text-base tracking-tight">TruthGuard</span>
              <span className="text-slate-400 font-normal text-xs">Chronos</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${
                connectionStatus === "connected"
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : connectionStatus === "checking"
                  ? "bg-amber-50 border-amber-200 text-amber-700"
                  : "bg-rose-50 border-rose-200 text-rose-700"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  connectionStatus === "connected"
                    ? "bg-emerald-500"
                    : connectionStatus === "checking"
                    ? "bg-amber-500 animate-pulse"
                    : "bg-rose-500"
                }`}
              />
              {connectionStatus === "connected"
                ? "Server online"
                : connectionStatus === "checking"
                ? "Checking..."
                : "Server offline"}
            </span>

            <button
              onClick={checkConnection}
              disabled={isLoadingConnection}
              className="px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 transition-colors shadow-2xs disabled:opacity-50"
            >
              Retry
            </button>
          </div>
        </header>

        {/* ── Hero Heading ── */}
        <section className="space-y-1.5 pt-1">
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-slate-900 leading-[1.15]">
            Ask your policies.<br />
            Get answers you can trace.
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 max-w-xl leading-relaxed">
            Upload policy documents, then ask a question. Every answer is cited, challenged and
            checked for conflicts between versions.
          </p>
        </section>

        {/* ── Navigation Tabs ── */}
        <div className="flex border-b border-slate-200 gap-4 sm:gap-6 pt-1">
          <button
            onClick={() => setActiveTab("ask")}
            className={`pb-3 px-1 text-xs sm:text-sm font-bold flex items-center gap-2 border-b-2 transition-all ${
              activeTab === "ask"
                ? "border-[#0d4a3e] text-[#0d4a3e]"
                : "border-transparent text-slate-400 hover:text-slate-700"
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
            Ask Policies & Verify
          </button>

          <button
            onClick={() => setActiveTab("compare")}
            className={`pb-3 px-1 text-xs sm:text-sm font-bold flex items-center gap-2 border-b-2 transition-all ${
              activeTab === "compare"
                ? "border-[#0d4a3e] text-[#0d4a3e]"
                : "border-transparent text-slate-400 hover:text-slate-700"
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
            Compare Two Documents
            <span className="text-[10px] font-bold bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full uppercase tracking-wider">
              Feature
            </span>
          </button>
        </div>

        {/* ── Tab Content: Ask Policies & Verify ── */}
        {activeTab === "ask" && (
          <div className="space-y-7">
        {/* ── Two Column Layout ── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
          
          {/* ── LEFT: Documents Card ── */}
          <div className="lg:col-span-4 border border-slate-200 rounded-2xl p-5 bg-white space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-900">Documents</h2>
              <span className="text-xs text-slate-400 font-normal">
                {uploadedDocs.length} uploaded
              </span>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt"
              onChange={handleFileChange}
              className="hidden"
            />

            {/* Dropzone */}
            {!selectedFile ? (
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragging(false);
                  if (e.dataTransfer.files?.[0]) validateAndSetFile(e.dataTransfer.files[0]);
                }}
                className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
                  isDragging
                    ? "border-emerald-400 bg-emerald-50/50"
                    : "border-emerald-300/80 bg-emerald-50/20 hover:bg-emerald-50/40"
                }`}
              >
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-emerald-700 mb-1">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                </div>
                <p className="text-xs font-semibold text-slate-800">Drop files here</p>
                <p className="text-[11px] text-slate-400 mt-0.5 mb-3">PDF or TXT</p>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
                  className="px-3.5 py-1 text-xs font-medium rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 shadow-2xs"
                >
                  Browse files
                </button>
              </div>
            ) : (
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-900 truncate">{selectedFile.name}</p>
                    <p className="text-[11px] text-slate-400">{(selectedFile.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button
                    onClick={handleRemoveFile}
                    disabled={isUploading}
                    className="text-slate-400 hover:text-rose-600 text-xs p-1"
                  >
                    ✕
                  </button>
                </div>
                <button
                  onClick={handleUpload}
                  disabled={isUploading}
                  className="w-full py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white flex items-center justify-center gap-1.5 shadow-2xs disabled:opacity-50"
                >
                  {isUploading ? <><Spinner size="h-3 w-3" /> Uploading…</> : "Upload Document"}
                </button>
              </div>
            )}

            {uploadFeedback && (
              <p
                className={`text-[11px] font-medium leading-relaxed ${
                  uploadFeedback.type === "success" ? "text-emerald-700" : "text-rose-700"
                }`}
              >
                {uploadFeedback.message}
              </p>
            )}

            {/* Uploaded Documents List */}
            {uploadedDocs.length > 0 && (
              <div className="pt-1 space-y-1.5">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                  Uploaded List ({uploadedDocs.length})
                </p>
                <ul className="space-y-1 max-h-36 overflow-y-auto pr-1">
                  {uploadedDocs.map((doc, idx) => (
                    <li
                      key={idx}
                      className="text-xs text-slate-700 truncate py-1 px-2 rounded-md bg-slate-50 border border-slate-100 flex items-center gap-1.5"
                      title={doc.filename}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                      <span className="truncate">{doc.filename}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* ── RIGHT: Ask a Question Card ── */}
          <div className="lg:col-span-8 border border-slate-200 rounded-2xl p-5 bg-white space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-900">Ask a question</h2>
              <span className="text-xs text-slate-400 font-normal hidden sm:inline">
                Retrieve · Synthesize · Critique · Arbitrate
              </span>
            </div>

            {/* Input area */}
            <div className="space-y-3">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAsk();
                }}
                rows={4}
                placeholder="What are the rules for travel by Vande Bharat Express on official tour?"
                className="w-full text-sm p-4 rounded-xl border border-slate-200 bg-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-600 focus:border-emerald-600 resize-none min-h-[140px] leading-relaxed text-slate-800"
              />

              {/* Bottom bar with Try buttons & Submit */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs text-slate-400 font-normal mr-1">Try</span>
                  {DEMO_CASES.map((d) => (
                    <button
                      key={d.id}
                      onClick={() => {
                        setQuestion(d.question);
                        handleAsk(d.question);
                      }}
                      className="px-3 py-1.5 rounded-full border border-slate-200 bg-white hover:border-slate-300 text-xs text-slate-700 flex items-center gap-1.5 transition-colors font-normal shadow-2xs"
                    >
                      <span className={`w-2 h-2 rounded-full ${d.dotColor}`} />
                      {d.label}
                    </button>
                  ))}
                </div>

                <button
                  onClick={() => handleAsk()}
                  disabled={isAsking || !question.trim() || connectionStatus !== "connected"}
                  className="px-5 py-2.5 rounded-xl bg-[#6b9080] hover:bg-[#587c6e] text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors shadow-xs disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap self-end sm:self-auto"
                >
                  {isAsking ? (
                    <>
                      <Spinner size="h-3.5 w-3.5" /> Analyzing…
                    </>
                  ) : (
                    "Ask TruthGuard"
                  )}
                </button>
              </div>
            </div>

            {/* Error Message */}
            {askError && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700">
                {askError}
              </div>
            )}

            {/* Results Section */}
            {askResult && !isAsking && (
              <div className="space-y-4 pt-3 border-t border-slate-100">
                <div
                  className={`rounded-2xl border p-5 space-y-3 ${
                    askResult.outcome === "RESOLVED"
                      ? "bg-emerald-50/60 border-emerald-200"
                      : askResult.outcome === "CONFLICT"
                      ? "bg-amber-50/60 border-amber-200"
                      : "bg-slate-100/70 border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <OutcomeBadge outcome={askResult.outcome} />
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-700 shadow-2xs">
                      Critic: {askResult.critic_status}
                    </span>
                  </div>

                  <p className="text-xs sm:text-sm text-slate-700 leading-relaxed font-normal">
                    {askResult.explanation}
                  </p>

                  {askResult.resolution_basis && (
                    <p className="text-xs text-slate-500 italic border-t border-slate-200/60 pt-2">
                      <span className="font-semibold not-italic text-slate-600">Resolution basis: </span>
                      {askResult.resolution_basis}
                    </p>
                  )}
                </div>

                {askResult.final_answer && (
                  <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">Synthesized Answer</h3>
                    <div className="text-xs sm:text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">
                      {askResult.final_answer}
                    </div>
                  </div>
                )}

                {askResult.outcome === "ABSTAIN" && askResult.abstention_reason && (
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-600">
                    <span className="font-bold text-slate-700">Abstention reason: </span>
                    {askResult.abstention_reason}
                  </div>
                )}

                {askResult.citations.length > 0 && (
                  <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-2.5">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                      Citations ({askResult.citations.length})
                    </h3>
                    <ol className="space-y-2 text-xs">
                      {askResult.citations.map((c) => (
                        <li key={c.citation_id} className="flex gap-2.5 items-start">
                          <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-800 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                            {c.citation_id}
                          </span>
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-800 truncate">{c.document_title || c.filename}</p>
                            {c.effective_or_issue_date && (
                              <p className="text-[11px] text-slate-400">Date: {c.effective_or_issue_date}</p>
                            )}
                            {c.quoted_snippet && (
                              <p className="text-[11px] text-slate-600 italic border-l-2 border-emerald-300 pl-2 mt-0.5">
                                "{c.quoted_snippet.slice(0, 160)}…"
                              </p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {askResult.conflicting_evidence.length > 0 && (
                  <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2">
                    <h3 className="text-xs font-bold text-amber-900 uppercase tracking-wide">
                      Conflicting Evidence ({askResult.conflicting_evidence.length})
                    </h3>
                    <ul className="space-y-2 text-xs text-amber-800">
                      {askResult.conflicting_evidence.map((cf, i) => (
                        <li key={i} className="space-y-0.5">
                          <p className="font-semibold text-amber-900">• {cf.issue_type?.replace(/_/g, " ")}</p>
                          <p className="text-amber-800">{cf.description}</p>
                          {cf.evidence && <p className="italic text-amber-600">Evidence: {cf.evidence.slice(0, 140)}</p>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── Provenance Graph Card ── */}
        <section className="border border-slate-200 rounded-2xl p-5 bg-white space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-bold text-slate-900">Provenance graph</h2>
              <span className="text-xs text-slate-400 font-normal">
                {graphNodes.length} documents · {graphEdges.length} links
              </span>
            </div>

            <button
              onClick={handleRebuildAndRefreshGraph}
              disabled={isRebuildingGraph || isLoadingDocs}
              className="px-3.5 py-1 text-xs font-medium rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 shadow-2xs transition-colors disabled:opacity-50"
            >
              {isRebuildingGraph ? "Rebuilding…" : "Rebuild"}
            </button>
          </div>

          {/* Graph area */}
          <div className="border border-slate-100 rounded-xl bg-slate-50/60 p-4 min-h-[320px] flex flex-col items-center justify-center relative overflow-hidden">
            {graphNodes.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center p-6 space-y-3">
                {/* 3 nodes connection graphic matching image */}
                <div className="flex flex-col items-center">
                  <div className="w-5 h-5 rounded-full border-2 border-emerald-600/80 bg-white" />
                  <div className="w-px h-6 border-l border-dashed border-slate-300" />
                  <div className="flex items-center gap-8 -mt-1">
                    <div className="w-5 h-5 rounded-full border-2 border-slate-300 bg-white" />
                    <div className="w-5 h-5 rounded-full border-2 border-slate-300 bg-white" />
                  </div>
                </div>

                <div className="pt-2">
                  <h3 className="text-xs font-bold text-slate-800">Your graph appears here</h3>
                  <p className="text-[11px] text-slate-400 max-w-sm text-center leading-relaxed mt-0.5">
                    Upload documents and TruthGuard will map which policies supersede, amend or conflict with each other.
                  </p>
                </div>
              </div>
            ) : (
              <div className="w-full space-y-3">
                {/* Graph filters */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide mr-1">
                      Filter:
                    </span>
                    <button
                      onClick={() => setGraphFilter("ALL")}
                      className={`px-2.5 py-1 text-[11px] font-medium rounded-lg border transition-colors ${
                        graphFilter === "ALL"
                          ? "bg-slate-900 text-white border-slate-900"
                          : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      All ({graphEdges.length})
                    </button>
                    {(["SUPERSEDES", "AMENDS", "SAME_POLICY", "RELATED_TO"] as const).map((type) => {
                      const cfg = RELATIONSHIP_CONFIG[type];
                      const count = graphEdges.filter((e) => (e.relationship || e.type) === type).length;
                      const isActive = graphFilter === type;
                      return (
                        <button
                          key={type}
                          onClick={() => setGraphFilter(type)}
                          className={`px-2 py-1 text-[11px] font-medium rounded-lg border flex items-center gap-1.5 transition-colors ${
                            isActive
                              ? `${cfg.badgeBg} ${cfg.badgeText} ${cfg.border} ring-1 ring-offset-1`
                              : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                          }`}
                        >
                          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: cfg.color }} />
                          {type} ({count})
                        </button>
                      );
                    })}
                  </div>

                  <p className="text-[11px] text-slate-400 hidden sm:block">
                    Drag nodes to reposition · Click to inspect
                  </p>
                </div>

                {/* SVG Visualizer */}
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-2xs relative">
                  <svg
                    ref={svgRef}
                    viewBox="0 0 860 480"
                    className="w-full h-[400px] cursor-grab active:cursor-grabbing select-none"
                    onMouseMove={handleSvgMouseMove}
                    onMouseUp={handleSvgMouseUp}
                    onMouseLeave={handleSvgMouseUp}
                  >
                    <defs>
                      <marker id="marker-SUPERSEDES" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 1 L 10 5 L 0 9 z" fill="#ef4444" />
                      </marker>
                      <marker id="marker-AMENDS" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 1 L 10 5 L 0 9 z" fill="#f59e0b" />
                      </marker>
                      <marker id="marker-SAME_POLICY" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
                      </marker>
                      <marker id="marker-RELATED_TO" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 1 L 10 5 L 0 9 z" fill="#6366f1" />
                      </marker>
                      <marker id="marker-default" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 1 L 10 5 L 0 9 z" fill="#94a3b8" />
                      </marker>
                    </defs>

                    {/* Background subtle grid */}
                    <g opacity="0.25">
                      {Array.from({ length: 18 }).map((_, i) => (
                        <line key={`v-${i}`} x1={i * 50} y1="0" x2={i * 50} y2="480" stroke="#cbd5e1" strokeWidth="0.5" strokeDasharray="2 4" />
                      ))}
                      {Array.from({ length: 10 }).map((_, i) => (
                        <line key={`h-${i}`} x1="0" y1={i * 50} x2="860" y2={i * 50} stroke="#cbd5e1" strokeWidth="0.5" strokeDasharray="2 4" />
                      ))}
                    </g>

                    {/* Edges */}
                    {graphEdges
                      .filter((e) => graphFilter === "ALL" || (e.relationship || e.type) === graphFilter)
                      .map((e, i) => {
                        const p1 = nodePositions[e.source];
                        const p2 = nodePositions[e.target];
                        if (!p1 || !p2) return null;
                        const rel = (e.relationship || e.type || "RELATED_TO").toUpperCase();
                        const cfg = RELATIONSHIP_CONFIG[rel] || RELATIONSHIP_CONFIG.RELATED_TO;
                        const dx = p2.x - p1.x;
                        const dy = p2.y - p1.y;
                        const dist = Math.hypot(dx, dy) || 1;
                        const R = 22;
                        const ux = dx / dist;
                        const uy = dy / dist;
                        const sx = p1.x + ux * R;
                        const sy = p1.y + uy * R;
                        const tx = p2.x - ux * (R + 8);
                        const ty = p2.y - uy * (R + 8);
                        const isConnected = selectedGraphNodeId
                          ? e.source === selectedGraphNodeId || e.target === selectedGraphNodeId
                          : false;
                        const opacity = selectedGraphNodeId ? (isConnected ? 1 : 0.2) : 0.85;
                        const mx = (sx + tx) / 2;
                        const my = (sy + ty) / 2;

                        return (
                          <g key={`edge-${i}`} opacity={opacity} className="transition-opacity">
                            <line
                              x1={sx}
                              y1={sy}
                              x2={tx}
                              y2={ty}
                              stroke={cfg.color}
                              strokeWidth={isConnected ? cfg.strokeWidth + 1.5 : cfg.strokeWidth}
                              strokeDasharray={cfg.dash === "none" ? undefined : cfg.dash}
                              markerEnd={`url(#marker-${rel})`}
                            />
                            <g transform={`translate(${mx}, ${my})`}>
                              <rect x="-30" y="-7" width="60" height="14" rx="7" fill="#ffffff" stroke={cfg.color} strokeWidth="1" />
                              <text textAnchor="middle" y="3" fontSize="7" fontWeight="bold" fill={cfg.color}>
                                {rel}
                              </text>
                            </g>
                          </g>
                        );
                      })}

                    {/* Nodes */}
                    {graphNodes.map((n) => {
                      const p = nodePositions[n.id];
                      if (!p) return null;
                      const isSelected = selectedGraphNodeId === n.id;
                      const isConnected = selectedGraphNodeId
                        ? graphEdges.some(
                            (e) =>
                              (e.source === selectedGraphNodeId && e.target === n.id) ||
                              (e.target === selectedGraphNodeId && e.source === n.id)
                          )
                        : false;
                      const isDimmed = selectedGraphNodeId ? !isSelected && !isConnected : false;
                      const hasEdges = graphEdges.some((e) => e.source === n.id || e.target === n.id);
                      const ext = (n.filename || n.id).split(".").pop()?.toUpperCase()?.slice(0, 3) || "DOC";
                      const rawName = n.original_filename || n.filename || n.id;
                      const truncatedName = rawName.length > 18 ? rawName.slice(0, 16) + "…" : rawName;

                      return (
                        <g
                          key={n.id}
                          className="cursor-pointer"
                          onMouseDown={(e) => handleNodeMouseDown(n.id, e)}
                          onClick={() => setSelectedGraphNodeId(n.id)}
                          opacity={isDimmed ? 0.35 : 1}
                        >
                          <title>{`${rawName}\nID: ${n.document_identifier || "None"}\nDate: ${n.effective_date || "Unknown"}`}</title>
                          {isSelected && (
                            <circle cx={p.x} cy={p.y} r={28} fill="none" stroke="#059669" strokeWidth={2} strokeDasharray="3 2" />
                          )}
                          <circle
                            cx={p.x}
                            cy={p.y}
                            r={20}
                            fill={isSelected ? "#0d4a3e" : isConnected ? "#ecfdf5" : "#ffffff"}
                            stroke={isSelected ? "#0d4a3e" : hasEdges ? "#059669" : "#cbd5e1"}
                            strokeWidth={hasEdges ? 2 : 1.5}
                          />
                          <text
                            x={p.x}
                            y={p.y + 4}
                            textAnchor="middle"
                            fontSize="8.5"
                            fontWeight="800"
                            fill={isSelected ? "#ffffff" : isConnected ? "#065f46" : "#475569"}
                          >
                            {ext}
                          </text>
                          <text
                            x={p.x}
                            y={p.y + 32}
                            textAnchor="middle"
                            fontSize="9.5"
                            fontWeight={isSelected ? "700" : "600"}
                            fill={isSelected ? "#047857" : "#1e293b"}
                          >
                            {truncatedName}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>

                {/* Selected Node Details Box */}
                {(() => {
                  const selectedNode = graphNodes.find((n) => n.id === selectedGraphNodeId);
                  if (!selectedNode) return null;
                  const outgoing = graphEdges.filter((e) => e.source === selectedNode.id);
                  const incoming = graphEdges.filter((e) => e.target === selectedNode.id);
                  const name = selectedNode.original_filename || selectedNode.filename || selectedNode.id;

                  return (
                    <div className="p-4 bg-white border border-slate-200 rounded-xl space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900 text-sm">{name}</span>
                        <button
                          onClick={() => setSelectedGraphNodeId(null)}
                          className="text-slate-400 hover:text-slate-600"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] text-slate-600 pt-1">
                        <div><span className="text-slate-400">ID:</span> {selectedNode.document_identifier || "—"}</div>
                        <div><span className="text-slate-400">Version:</span> {selectedNode.version || "—"}</div>
                        <div><span className="text-slate-400">Date:</span> {selectedNode.effective_date || selectedNode.issue_date || "—"}</div>
                        <div><span className="text-slate-400">Scope:</span> {selectedNode.scope || "—"}</div>
                      </div>
                      {(outgoing.length > 0 || incoming.length > 0) && (
                        <div className="pt-2 border-t border-slate-100 space-y-1">
                          <p className="text-[10px] font-bold text-slate-400 uppercase">Provenance Edges</p>
                          {outgoing.map((e, idx) => (
                            <p key={`o-${idx}`} className="text-[11px] text-slate-700">
                              • <strong className="text-rose-600">{e.relationship}</strong> → {e.target}
                            </p>
                          ))}
                          {incoming.map((e, idx) => (
                            <p key={`i-${idx}`} className="text-[11px] text-slate-700">
                              • {e.source} → <strong className="text-amber-600">{e.relationship}</strong> → THIS
                            </p>
                          ))}
                        </div>
                      )}

                      <div className="pt-2 border-t border-slate-100 flex items-center justify-end">
                        <button
                          onClick={() => {
                            setCompareDocA(selectedNode.saved_filename || selectedNode.id);
                            setActiveTab("compare");
                          }}
                          className="px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-lg text-xs font-semibold hover:bg-emerald-100 flex items-center gap-1.5 transition-colors shadow-2xs"
                        >
                          <span>⇄</span> Compare in Two Documents Tab
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        </section>
        </div>
        )}

        {/* ── Tab Content: Compare Two Documents ── */}
        {activeTab === "compare" && (
          <div className="space-y-6">
            
            {/* Document Selection & Control Card */}
            <div className="border border-slate-200 rounded-2xl p-6 bg-white space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
                <div>
                  <h2 className="text-base font-bold text-slate-900">Compare Two Documents</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Select two uploaded policy documents to evaluate metadata, graph relationships, rule differences, and conflict resolution.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-medium">
                    {uploadedDocs.length} documents available
                  </span>
                </div>
              </div>

              {uploadedDocs.length < 2 ? (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800 space-y-2">
                  <p className="font-semibold">⚠️ Need at least two documents</p>
                  <p>
                    Please upload at least two policy documents to use the comparison tool. You can upload documents in the "Ask Policies & Verify" tab.
                  </p>
                  <button
                    onClick={() => setActiveTab("ask")}
                    className="mt-1 px-3 py-1.5 bg-amber-700 text-white rounded-lg font-medium text-xs hover:bg-amber-800 transition-colors shadow-2xs"
                  >
                    Go to Upload Tab →
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Dropdowns Row */}
                  <div className="grid grid-cols-1 md:grid-cols-11 gap-3 items-center">
                    {/* Document A Selector */}
                    <div className="md:col-span-5 space-y-1.5">
                      <label className="block text-xs font-bold text-slate-700">
                        Document A (Reference)
                      </label>
                      <select
                        value={compareDocA}
                        onChange={(e) => setCompareDocA(e.target.value)}
                        className="w-full text-xs sm:text-sm p-3 rounded-xl border border-slate-200 bg-white focus:outline-none focus:ring-1 focus:ring-emerald-600 focus:border-emerald-600 text-slate-800 truncate"
                      >
                        {uploadedDocs.map((doc, idx) => (
                          <option key={`a-${idx}`} value={doc.saved_filename || doc.filename}>
                            {doc.filename}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Swap Button */}
                    <div className="md:col-span-1 flex justify-center pt-5 sm:pt-4">
                      <button
                        type="button"
                        onClick={handleSwapCompareDocs}
                        title="Swap Document A and Document B"
                        className="p-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-600 transition-colors shadow-2xs"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                        </svg>
                      </button>
                    </div>

                    {/* Document B Selector */}
                    <div className="md:col-span-5 space-y-1.5">
                      <label className="block text-xs font-bold text-slate-700">
                        Document B (Comparative)
                      </label>
                      <select
                        value={compareDocB}
                        onChange={(e) => setCompareDocB(e.target.value)}
                        className="w-full text-xs sm:text-sm p-3 rounded-xl border border-slate-200 bg-white focus:outline-none focus:ring-1 focus:ring-emerald-600 focus:border-emerald-600 text-slate-800 truncate"
                      >
                        {uploadedDocs.map((doc, idx) => (
                          <option key={`b-${idx}`} value={doc.saved_filename || doc.filename}>
                            {doc.filename}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Preset Pills & Action Button */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-xs text-slate-400 font-normal mr-1">Sample cases:</span>
                      <button
                        onClick={() => handleSampleCompare("supersession")}
                        className="px-3 py-1 rounded-full border border-slate-200 bg-white hover:border-slate-300 text-xs text-slate-700 flex items-center gap-1.5 transition-colors shadow-2xs"
                      >
                        <span className="w-2 h-2 rounded-full bg-emerald-500" />
                        Supersession (2022 vs 2025)
                      </button>
                      <button
                        onClick={() => handleSampleCompare("scope")}
                        className="px-3 py-1 rounded-full border border-slate-200 bg-white hover:border-slate-300 text-xs text-slate-700 flex items-center gap-1.5 transition-colors shadow-2xs"
                      >
                        <span className="w-2 h-2 rounded-full bg-amber-500" />
                        Scope Conflict (Global vs APAC)
                      </button>
                      <button
                        onClick={() => handleSampleCompare("empty")}
                        className="px-3 py-1 rounded-full border border-slate-200 bg-white hover:border-slate-300 text-xs text-slate-700 flex items-center gap-1.5 transition-colors shadow-2xs"
                      >
                        <span className="w-2 h-2 rounded-full bg-slate-400" />
                        Empty Document (Abstain)
                      </button>
                    </div>

                    <button
                      onClick={() => handleCompare()}
                      disabled={isComparing || !compareDocA || !compareDocB || connectionStatus !== "connected"}
                      className="px-6 py-2.5 rounded-xl bg-[#0d4a3e] hover:bg-[#09392f] text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors shadow-xs disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap self-end sm:self-auto"
                    >
                      {isComparing ? (
                        <>
                          <Spinner size="h-3.5 w-3.5" /> Comparing Documents…
                        </>
                      ) : (
                        "Compare Documents"
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Error Message */}
            {compareError && (
              <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700">
                {compareError}
              </div>
            )}

            {/* Results Area */}
            {compareResult && !isComparing && (
              <div className="space-y-6">
                
                {/* 1. Comparison Outcome & Precedence Banner */}
                <div
                  className={`rounded-2xl border p-5 sm:p-6 space-y-4 ${
                    compareResult.outcome === "RESOLVED"
                      ? "bg-emerald-50/70 border-emerald-200"
                      : compareResult.outcome === "CONFLICT"
                      ? "bg-amber-50/70 border-amber-200"
                      : "bg-slate-100/80 border-slate-300"
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/60 pb-3">
                    <div className="flex items-center gap-3 flex-wrap">
                      <OutcomeBadge outcome={compareResult.outcome} />
                      <RelationshipBadge
                        relationship={compareResult.relationship}
                        direction={compareResult.relationship_direction}
                        evidence={compareResult.relationship_evidence}
                      />
                    </div>

                    <span className="text-xs text-slate-500 font-mono">
                      {compareResult.document_a.filename} ⟷ {compareResult.document_b.filename}
                    </span>
                  </div>

                  <p className="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">
                    {compareResult.explanation}
                  </p>

                  <div className="pt-2 border-t border-slate-200/60 text-[11px] text-slate-500 flex items-start gap-1.5">
                    <span className="font-bold text-slate-600 flex-shrink-0">Audit Precedence Policy:</span>
                    <span>
                      TruthGuard strictly requires explicit evidence (such as a supersession clause or parent policy amendment link) to resolve conflicts. In the absence of explicit precedence, potential conflicts and rule differences are surfaced without speculation.
                    </span>
                  </div>
                </div>

                {/* 2. Side-by-Side Metadata & Extracted Text Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  {/* Document A */}
                  <div className="border border-slate-200 rounded-2xl p-5 bg-white space-y-4 shadow-2xs">
                    <div className="border-b border-slate-100 pb-3 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                          Document A (Reference)
                        </span>
                        {compareResult.document_a.is_empty && (
                          <span className="text-[10px] font-bold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">
                            Empty Content
                          </span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold text-slate-900 truncate" title={compareResult.document_a.filename}>
                        {compareResult.document_a.metadata.document_title || compareResult.document_a.filename}
                      </h3>
                      <p className="text-[11px] text-slate-400 font-mono truncate">
                        File: {compareResult.document_a.filename}
                      </p>
                    </div>

                    {/* Metadata Grid */}
                    <div className="space-y-2">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide block">
                        Document Metadata
                      </span>
                      <div className="grid grid-cols-2 gap-2 text-xs bg-slate-50/80 p-3 rounded-xl border border-slate-200/80">
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Identifier</span>
                          <span className="font-semibold text-slate-800 break-words">
                            {compareResult.document_a.metadata.policy_or_document_identifier || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Version</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_a.metadata.version || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Effective Date</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_a.metadata.effective_date || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Issue Date</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_a.metadata.issue_date || "Not specified"}
                          </span>
                        </div>
                        <div className="col-span-2">
                          <span className="text-[10px] font-semibold text-slate-400 block">Scope</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_a.metadata.scope || "Not specified"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Extracted Passages */}
                    <div className="space-y-2 pt-1">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide block">
                        Relevant Extracted Passages ({compareResult.document_a.passages?.length || 0})
                      </span>
                      {compareResult.document_a.passages && compareResult.document_a.passages.length > 0 ? (
                        <div className="space-y-2">
                          {compareResult.document_a.passages.map((p, idx) => (
                            <div
                              key={`p-a-${idx}`}
                              className="p-3 bg-slate-50 border-l-2 border-[#0d4a3e] rounded-r-xl text-xs text-slate-700 leading-relaxed italic"
                            >
                              "{p}"
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 italic p-3 bg-slate-50 rounded-xl">
                          {compareResult.document_a.is_empty
                            ? "Document is empty. No text passages extracted."
                            : "No substantive rule passages found."}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Document B */}
                  <div className="border border-slate-200 rounded-2xl p-5 bg-white space-y-4 shadow-2xs">
                    <div className="border-b border-slate-100 pb-3 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                          Document B (Comparative)
                        </span>
                        {compareResult.document_b.is_empty && (
                          <span className="text-[10px] font-bold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">
                            Empty Content
                          </span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold text-slate-900 truncate" title={compareResult.document_b.filename}>
                        {compareResult.document_b.metadata.document_title || compareResult.document_b.filename}
                      </h3>
                      <p className="text-[11px] text-slate-400 font-mono truncate">
                        File: {compareResult.document_b.filename}
                      </p>
                    </div>

                    {/* Metadata Grid */}
                    <div className="space-y-2">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide block">
                        Document Metadata
                      </span>
                      <div className="grid grid-cols-2 gap-2 text-xs bg-slate-50/80 p-3 rounded-xl border border-slate-200/80">
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Identifier</span>
                          <span className="font-semibold text-slate-800 break-words">
                            {compareResult.document_b.metadata.policy_or_document_identifier || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Version</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_b.metadata.version || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Effective Date</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_b.metadata.effective_date || "Not specified"}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-slate-400 block">Issue Date</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_b.metadata.issue_date || "Not specified"}
                          </span>
                        </div>
                        <div className="col-span-2">
                          <span className="text-[10px] font-semibold text-slate-400 block">Scope</span>
                          <span className="font-semibold text-slate-800">
                            {compareResult.document_b.metadata.scope || "Not specified"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Extracted Passages */}
                    <div className="space-y-2 pt-1">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide block">
                        Relevant Extracted Passages ({compareResult.document_b.passages?.length || 0})
                      </span>
                      {compareResult.document_b.passages && compareResult.document_b.passages.length > 0 ? (
                        <div className="space-y-2">
                          {compareResult.document_b.passages.map((p, idx) => (
                            <div
                              key={`p-b-${idx}`}
                              className="p-3 bg-slate-50 border-l-2 border-[#0d4a3e] rounded-r-xl text-xs text-slate-700 leading-relaxed italic"
                            >
                              "{p}"
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 italic p-3 bg-slate-50 rounded-xl">
                          {compareResult.document_b.is_empty
                            ? "Document is empty. No text passages extracted."
                            : "No substantive rule passages found."}
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                {/* 3. Differences & Rule Analysis */}
                <div className="border border-slate-200 rounded-2xl p-5 bg-white space-y-4 shadow-2xs">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">Differences & Rule Analysis</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Potentially conflicting rules and metadata discrepancies between the documents.
                      </p>
                    </div>
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                      {compareResult.differences.length} analyzed
                    </span>
                  </div>

                  {compareResult.differences.length === 0 ? (
                    <div className="p-4 bg-slate-50 rounded-xl text-xs text-slate-500 italic text-center">
                      No differences identified between these documents.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {compareResult.differences.map((diff, idx) => (
                        <div
                          key={`diff-${idx}`}
                          className={`rounded-xl border p-4 space-y-2.5 transition-colors ${
                            diff.is_conflicting
                              ? "bg-amber-50/60 border-amber-300"
                              : "bg-slate-50/70 border-slate-200"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <span className="text-xs font-bold text-slate-800">{diff.category}</span>
                            {diff.is_conflicting ? (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800 border border-amber-300">
                                <span>⚠️</span> Potential Conflict — No Explicit Precedence
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                <span>✓</span> Resolved / Compatible
                              </span>
                            )}
                          </div>

                          <p className="text-xs text-slate-700 leading-relaxed font-normal">
                            {diff.description}
                          </p>

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs pt-1">
                            <div className="p-2.5 rounded-lg bg-white border border-slate-200 space-y-0.5">
                              <span className="text-[10px] font-bold text-slate-400 uppercase block truncate">
                                {compareResult.document_a.filename}
                              </span>
                              <span className="text-slate-800 font-medium whitespace-pre-wrap break-words">
                                {diff.doc_a_value}
                              </span>
                            </div>
                            <div className="p-2.5 rounded-lg bg-white border border-slate-200 space-y-0.5">
                              <span className="text-[10px] font-bold text-slate-400 uppercase block truncate">
                                {compareResult.document_b.filename}
                              </span>
                              <span className="text-slate-800 font-medium whitespace-pre-wrap break-words">
                                {diff.doc_b_value}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 4. Source Filenames & Citations */}
                {compareResult.citations.length > 0 && (
                  <div className="border border-slate-200 rounded-2xl p-5 bg-white space-y-3 shadow-2xs">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                      Source Citations & Evidence ({compareResult.citations.length})
                    </h3>
                    <ol className="space-y-2.5 text-xs">
                      {compareResult.citations.map((c) => (
                        <li
                          key={`cit-${c.citation_id}`}
                          className="flex gap-3 items-start p-3 bg-slate-50 rounded-xl border border-slate-200/80"
                        >
                          <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-800 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                            {c.citation_id}
                          </span>
                          <div className="min-w-0 space-y-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="font-bold text-slate-800">{c.title || c.filename}</p>
                              <span className="text-[11px] text-slate-500 font-mono">Source: {c.filename}</span>
                              {c.date && <span className="text-[11px] text-slate-400">· Date: {c.date}</span>}
                            </div>
                            {c.snippet && (
                              <p className="text-[11px] text-slate-700 italic border-l-2 border-emerald-400 pl-2 mt-1">
                                "{c.snippet}"
                              </p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

              </div>
            )}
          </div>
        )}

      </main>
    </div>
  );
}
