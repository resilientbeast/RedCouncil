import { useCallback, useState } from "react";
import { useAuth } from "@clerk/clerk-react";
import type { UploadedDocument } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const MAX_DOCUMENTS = 3;
const ACCEPTED_EXTENSIONS = [".pdf", ".csv"];

interface UploadState {
  documents: UploadedDocument[];
  uploading: boolean;
  error: string | null;
}

export function useDocumentUpload() {
  const { getToken } = useAuth();
  const [state, setState] = useState<UploadState>({ documents: [], uploading: false, error: null });

  const upload = useCallback(
    async (files: FileList | File[]) => {
      const fileArray = Array.from(files);

      const roomLeft = MAX_DOCUMENTS - state.documents.length;
      if (roomLeft <= 0) {
        setState((s) => ({ ...s, error: `Up to ${MAX_DOCUMENTS} documents per decision.` }));
        return;
      }

      const toUpload = fileArray.slice(0, roomLeft).filter((f) =>
        ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext))
      );

      if (toUpload.length === 0) {
        setState((s) => ({ ...s, error: "Only .pdf and .csv files are accepted." }));
        return;
      }

      setState((s) => ({ ...s, uploading: true, error: null }));

      const uploaded: UploadedDocument[] = [];
      const token = await getToken();

      for (const file of toUpload) {
        try {
          const formData = new FormData();
          formData.append("file", file);
          const res = await fetch(`${API_BASE}/api/v1/documents`, {
            method: "POST",
            body: formData,
            headers: token ? { Authorization: `Bearer ${token}` } : undefined
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail ?? `Upload failed for ${file.name}`);
          }
          uploaded.push((await res.json()) as UploadedDocument);
        } catch (err) {
          setState((s) => ({
            ...s,
            uploading: false,
            error: err instanceof Error ? err.message : `Failed to upload ${file.name}`,
          }));
          return;
        }
      }

      setState((s) => ({ ...s, documents: [...s.documents, ...uploaded], uploading: false }));
    },
    [state.documents.length, getToken]
  );

  const remove = useCallback((documentId: string) => {
    setState((s) => ({ ...s, documents: s.documents.filter((d) => d.document_id !== documentId) }));
  }, []);

  const reset = useCallback(() => {
    setState({ documents: [], uploading: false, error: null });
  }, []);

  return { ...state, upload, remove, reset, maxDocuments: MAX_DOCUMENTS };
}
