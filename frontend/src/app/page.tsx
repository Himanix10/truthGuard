"use client";

import { useState, useEffect, useCallback, useRef } from "react";

const BACKEND_URL = "http://localhost:8000";

export default function Home() {
  // Backend Connection State
  const [connectionStatus, setConnectionStatus] = useState<
    "checking" | "connected" | "disconnected"
  >("checking");
  const [isLoadingConnection, setIsLoadingConnection] = useState<boolean>(true);

  // Document Upload State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [uploadFeedback, setUploadFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Check Backend Connection
  const checkConnection = useCallback(async () => {
    setIsLoadingConnection(true);
    setConnectionStatus("checking");

    try {
      const response = await fetch(`${BACKEND_URL}/health`, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
      });

      if (response.ok) {
        const data = await response.json();
        if (data && data.status === "healthy") {
          setConnectionStatus("connected");
        } else {
          setConnectionStatus("disconnected");
        }
      } else {
        setConnectionStatus("disconnected");
      }
    } catch {
      setConnectionStatus("disconnected");
    } finally {
      setIsLoadingConnection(false);
    }
  }, []);

  useEffect(() => {
    checkConnection();
  }, [checkConnection]);

  // File Size Formatter Utility
  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Validate and select file (.pdf or .txt)
  const validateAndSetFile = (file: File) => {
    setUploadFeedback(null);
    const extension = file.name.split(".").pop()?.toLowerCase();

    if (extension !== "pdf" && extension !== "txt") {
      setUploadFeedback({
        type: "error",
        message: "Only PDF (.pdf) and Text (.txt) files are supported.",
      });
      return;
    }

    setSelectedFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setUploadFeedback(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  // Upload action calling the backend POST /upload endpoint
  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadFeedback(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(`${BACKEND_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json().catch(() => null);

      if (response.ok && data?.status === "success") {
        setUploadFeedback({
          type: "success",
          message: `"${data.original_filename}" uploaded successfully as ${data.saved_filename}.`,
        });
      } else {
        const errorMsg =
          data?.detail || "Failed to upload document. Please check the file format.";
        setUploadFeedback({
          type: "error",
          message: errorMsg,
        });
      }
    } catch {
      setUploadFeedback({
        type: "error",
        message: "Network error: Unable to connect to backend server at http://localhost:8000.",
      });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className="min-h-screen bg-white text-slate-900 flex flex-col justify-center items-center px-6 py-16">
      <div className="max-w-3xl w-full text-center space-y-8">
        {/* Status / Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-100 border border-slate-200 text-slate-700 text-xs font-semibold uppercase tracking-wider">
          Hackathon Prototype
        </div>

        {/* Project Title */}
        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-slate-900">
          TruthGuard-Chronos
        </h1>

        {/* Subtitle */}
        <p className="text-lg sm:text-xl font-medium text-blue-600">
          Temporal-Provenance Conflict Graph with Deep Agent Verification
        </p>

        {/* Short Description */}
        <p className="text-base sm:text-lg text-slate-600 leading-relaxed max-w-2xl mx-auto">
          AI-powered document verification that detects conflicting, outdated, and scope-mismatched policies before generating answers.
        </p>

        {/* Backend Connection Status Section */}
        <div>
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-4 bg-slate-50 border border-slate-200 rounded-xl max-w-md mx-auto w-full shadow-sm">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-3 w-3">
                {isLoadingConnection && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                )}
                <span
                  className={`relative inline-flex rounded-full h-3 w-3 ${
                    isLoadingConnection
                      ? "bg-amber-500"
                      : connectionStatus === "connected"
                      ? "bg-emerald-500"
                      : "bg-rose-500"
                  }`}
                ></span>
              </span>
              <span className="text-sm font-medium text-slate-700">
                {isLoadingConnection
                  ? "Checking connection..."
                  : connectionStatus === "connected"
                  ? "Backend Connected"
                  : "Backend Disconnected"}
              </span>
            </div>

            <button
              onClick={checkConnection}
              disabled={isLoadingConnection}
              className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-white border border-slate-300 text-slate-700 hover:bg-slate-100 active:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {isLoadingConnection ? "Checking..." : "Check Connection"}
            </button>
          </div>
        </div>

        {/* Document Upload Section */}
        <section className="bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-sm text-left space-y-5">
          <div>
            <h2 className="text-lg sm:text-xl font-bold text-slate-900">
              Document Ingestion & Verification
            </h2>
            <p className="text-xs sm:text-sm text-slate-500 mt-1">
              Select or drop policy documents to analyze temporal provenance and conflicting statements.
            </p>
          </div>

          {/* Hidden File Input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt"
            onChange={handleFileChange}
            className="hidden"
          />

          {/* Dropzone Area */}
          {!selectedFile ? (
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
                isDragging
                  ? "border-blue-500 bg-blue-50/50"
                  : "border-slate-300 hover:border-blue-400 hover:bg-slate-50/60 bg-slate-50/30"
              }`}
            >
              <div className="flex flex-col items-center justify-center space-y-3">
                <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
                  <svg
                    className="w-6 h-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    Click to select a file <span className="text-slate-500 font-normal">or drag & drop</span>
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Supported formats: PDF (.pdf), Plain Text (.txt)
                  </p>
                </div>
              </div>
            </div>
          ) : (
            /* Selected File Card */
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-slate-50 border border-slate-200 rounded-xl">
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="w-10 h-10 rounded-lg bg-blue-100 flex-shrink-0 flex items-center justify-center text-blue-600 font-bold text-xs uppercase">
                    {selectedFile.name.split(".").pop()}
                  </div>
                  <div className="truncate">
                    <p className="text-sm font-semibold text-slate-900 truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-xs text-slate-500">
                      {formatFileSize(selectedFile.size)}
                    </p>
                  </div>
                </div>

                <button
                  onClick={handleRemoveFile}
                  disabled={isUploading}
                  className="flex-shrink-0 p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors disabled:opacity-50"
                  title="Remove file"
                  aria-label="Remove file"
                >
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>

              {/* Upload Action Button */}
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={handleRemoveFile}
                  disabled={isUploading}
                  className="px-4 py-2 text-xs font-semibold rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleUpload}
                  disabled={isUploading}
                  className="px-5 py-2 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-all shadow-sm flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {isUploading ? (
                    <>
                      <svg
                        className="animate-spin h-3.5 w-3.5 text-white"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                      <span>Uploading...</span>
                    </>
                  ) : (
                    <span>Upload Document</span>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Feedback Alerts */}
          {uploadFeedback && (
            <div
              className={`p-3.5 rounded-xl text-xs flex items-center gap-2.5 transition-all ${
                uploadFeedback.type === "success"
                  ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
                  : "bg-rose-50 border border-rose-200 text-rose-800"
              }`}
            >
              {uploadFeedback.type === "success" ? (
                <svg
                  className="w-4 h-4 text-emerald-600 flex-shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <svg
                  className="w-4 h-4 text-rose-600 flex-shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              )}
              <span className="font-medium">{uploadFeedback.message}</span>
            </div>
          )}
        </section>

        {/* Feature Highlights / Clean Structure */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2 text-left">
          <div className="p-5 rounded-xl border border-slate-200 bg-slate-50/50">
            <h3 className="font-semibold text-slate-900 text-sm mb-1">Temporal Graph</h3>
            <p className="text-xs text-slate-500">Maps chronological precedence and policy validity windows across documents.</p>
          </div>
          <div className="p-5 rounded-xl border border-slate-200 bg-slate-50/50">
            <h3 className="font-semibold text-slate-900 text-sm mb-1">Conflict Detection</h3>
            <p className="text-xs text-slate-500">Identifies policy supersessions and jurisdiction/scope divergences.</p>
          </div>
          <div className="p-5 rounded-xl border border-slate-200 bg-slate-50/50">
            <h3 className="font-semibold text-slate-900 text-sm mb-1">Agent Verification</h3>
            <p className="text-xs text-slate-500">Deep multi-agent cross-examination for provenance-backed answers.</p>
          </div>
        </div>
      </div>
    </main>
  );
}
