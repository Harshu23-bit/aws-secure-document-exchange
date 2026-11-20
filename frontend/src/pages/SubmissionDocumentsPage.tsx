import { useRef, useState } from 'react'
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  ArrowLeft,
  Download,
  FileText,
  Image,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { documentService, submissionService } from '../lib/apiServices'
import { useAuth } from '../features/auth/useAuth'
import { useTenant } from '../features/tenants/useTenant'
import type {
  DocumentContentType,
  DocumentResponse,
} from '../types/api'

const PAGE_SIZE = 20
const MAX_FILE_SIZE = 10 * 1024 * 1024

const ACCEPTED_TYPES: Record<string, DocumentContentType> = {
  'application/pdf': 'application/pdf',
  'image/jpeg': 'image/jpeg',
  'image/png': 'image/png',
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail

    if (typeof detail === 'string') {
      return detail
    }
  }

  return error instanceof Error
    ? error.message
    : 'An unexpected error occurred.'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function formatDate(value: string): string {
  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return 'Unknown'
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function DocumentStatusBadge({
  status,
}: {
  status: DocumentResponse['status']
}) {
  const uploaded = status === 'UPLOADED'

  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
        uploaded
          ? 'bg-emerald-50 text-emerald-700'
          : 'bg-amber-50 text-amber-700'
      }`}
    >
      {uploaded ? 'Uploaded' : 'Pending upload'}
    </span>
  )
}

export default function SubmissionDocumentsPage() {
  const { submissionId } = useParams<{ submissionId: string }>()
  const { activeTenant, tenantContext } = useTenant()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [uploadError, setUploadError] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const [downloadingDocumentId, setDownloadingDocumentId] =
    useState<string | null>(null)

  const downloadingDocumentIdRef = useRef<string | null>(null)

  const tenantId = activeTenant?.tenant_id
  const userId = user?.userId
  const role = tenantContext?.role ?? activeTenant?.role

  const enabled = Boolean(tenantId && submissionId && userId)

  const submissionQuery = useQuery({
    queryKey: ['submission', userId, tenantId, submissionId],
    queryFn: () => submissionService.get(tenantId!, submissionId!),
    enabled,
  })

  const documentsQuery = useInfiniteQuery({
    queryKey: ['documents', userId, tenantId, submissionId, PAGE_SIZE],
    enabled: Boolean(userId && tenantId && submissionId),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      documentService.list(tenantId!, submissionId!, {
        limit: PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    getNextPageParam: (lastPage) =>
      lastPage.next_cursor ?? undefined,
  })

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const contentType = ACCEPTED_TYPES[file.type]

      if (!contentType) {
        throw new Error('Only PDF, JPEG, and PNG files are supported.')
      }

      if (file.size <= 0 || file.size > MAX_FILE_SIZE) {
        throw new Error('File size must be greater than 0 and at most 10 MB.')
      }

      const upload = await documentService.requestUpload(
        tenantId!,
        submissionId!,
        {
          filename: file.name,
          content_type: contentType,
          size_bytes: file.size,
        },
      )

      await documentService.uploadToS3(upload, file)

      return documentService.completeUpload(
        tenantId!,
        submissionId!,
        upload.document_id,
      )
    },
    onSuccess: async () => {
      setUploadError(null)

      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['documents', userId, tenantId, submissionId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['submissions', userId, tenantId],
        }),
      ])
    },
    onError: (error) => {
      setUploadError(getErrorMessage(error))
    },
  })

  async function handleDownload(documentId: string) {
    if (downloadingDocumentIdRef.current !== null) {
      return
    }

    downloadingDocumentIdRef.current = documentId
    setDownloadingDocumentId(documentId)
    setDownloadError(null)

    try {
      const result = await documentService.getDownloadUrl(
        tenantId!,
        submissionId!,
        documentId,
      )

      const link = document.createElement('a')
      link.href = result.download_url
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (error) {
      setDownloadError(getErrorMessage(error))
    } finally {
      downloadingDocumentIdRef.current = null
      setDownloadingDocumentId(null)
    }
  }

  function handleFileSelection(file?: File) {
    if (!file) return

    setUploadError(null)
    uploadMutation.mutate(file)

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const submission = submissionQuery.data
  const documents = documentsQuery.data?.pages.flatMap((page) => page.items) ?? []

  const canUpload =
    role === 'SUBMITTER' &&
    submission?.status === 'DRAFT'

  if (!submissionId || !tenantId) {
    return (
      <div className="rounded-xl border border-red-200 bg-white p-8 text-center">
        <p className="text-sm text-red-700">
          No active workspace or submission was selected.
        </p>
        <button
          onClick={() => navigate('/')}
          className="mt-4 text-sm font-medium text-blue-600"
        >
          Return to dashboard
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <button
          onClick={() => navigate('/')}
          className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
        >
          <ArrowLeft size={16} />
          Back to dashboard
        </button>

        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <FileText size={22} className="text-blue-600" />
              <h1 className="text-2xl font-semibold text-slate-900">
                Submission documents
              </h1>
            </div>

            <p className="mt-2 text-sm text-slate-500">
              {submission?.title || submissionId}
            </p>

            {submission && (
              <p className="mt-1 text-xs text-slate-400">
                {submission.submission_id} · {submission.status}
              </p>
            )}
          </div>

          {canUpload && (
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploadMutation.isPending ? (
                <LoaderCircle size={17} className="animate-spin" />
              ) : (
                <Upload size={17} />
              )}
              {uploadMutation.isPending ? 'Uploading...' : 'Upload document'}
            </button>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
            className="hidden"
            disabled={uploadMutation.isPending}
            onChange={(event) =>
              handleFileSelection(event.target.files?.[0])
            }
          />
        </div>
      </div>

      {submissionQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center">
          <LoaderCircle className="mx-auto animate-spin text-blue-600" size={28} />
          <p className="mt-3 text-sm text-slate-500">
            Loading submission...
          </p>
        </div>
      ) : submissionQuery.isError ? (
        <div className="rounded-xl border border-red-200 bg-white p-8">
          <p className="font-medium text-red-700">
            Unable to load submission
          </p>
          <p className="mt-2 text-sm text-slate-500">
            {getErrorMessage(submissionQuery.error)}
          </p>
          <button
            onClick={() => void submissionQuery.refetch()}
            className="mt-4 text-sm font-medium text-blue-600"
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          {!canUpload && role === 'SUBMITTER' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Uploading is available only while this submission is in Draft.
            </div>
          )}

          {role === 'REVIEWER' && (
            <div className="flex items-start gap-3 rounded-lg border border-blue-100 bg-blue-50 p-4">
              <ShieldCheck size={19} className="mt-0.5 shrink-0 text-blue-600" />
              <p className="text-sm text-blue-800">
                You can view documents according to the submission's workflow
                status. Only uploaded documents can be downloaded.
              </p>
            </div>
          )}

          {uploadError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              Upload failed: {uploadError}
            </div>
          )}

          {downloadError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              Download failed: {downloadError}
            </div>
          )}

          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-semibold text-slate-900">
                  Documents
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {documents.length} documents loaded
                </p>
              </div>

              <button
                onClick={() => void documentsQuery.refetch()}
                disabled={documentsQuery.isFetching}
                aria-label="Refresh documents"
                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
              >
                <RefreshCw
                  size={17}
                  className={documentsQuery.isFetching ? 'animate-spin' : ''}
                />
              </button>
            </div>

            {documentsQuery.isLoading ? (
              <div className="p-12 text-center">
                <LoaderCircle className="mx-auto animate-spin text-blue-600" size={26} />
                <p className="mt-3 text-sm text-slate-500">
                  Loading documents...
                </p>
              </div>
            ) : documentsQuery.isError && !documentsQuery.data ? (
              <div className="p-8 text-center">
                <p className="text-sm text-red-700">
                  {getErrorMessage(documentsQuery.error)}
                </p>
                <button
                  onClick={() => void documentsQuery.refetch()}
                  className="mt-3 text-sm font-medium text-blue-600"
                >
                  Retry
                </button>
              </div>
            ) : documents.length === 0 ? (
              <div className="p-12 text-center">
                <Image className="mx-auto text-slate-300" size={36} />
                <h3 className="mt-3 font-medium text-slate-800">
                  No documents yet
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  Documents associated with this submission will appear here.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {documents.map((document) => (
                  <div
                    key={document.document_id}
                    className="flex flex-col justify-between gap-4 px-5 py-4 sm:flex-row sm:items-center"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="rounded-lg bg-slate-100 p-2.5 text-slate-600">
                        <FileText size={20} />
                      </div>

                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-800">
                          {document.filename}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {formatBytes(document.size_bytes)} ·{' '}
                          {formatDate(document.created_at)}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <DocumentStatusBadge status={document.status} />

                      {document.status === 'UPLOADED' &&
                        role !== 'TENANT_ADMIN' && (
                          <button
                            onClick={() =>
                              void handleDownload(document.document_id)
                            }
                            disabled={downloadingDocumentId !== null}
                            aria-label={
                              downloadingDocumentId === document.document_id
                                ? `Downloading ${document.filename}`
                                : `Download ${document.filename}`
                            }
                            aria-busy={downloadingDocumentId === document.document_id}
                            className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {downloadingDocumentId === document.document_id ? (
                              <LoaderCircle size={17} className="animate-spin" />
                            ) : (
                              <Download size={17} />
                            )}
                          </button>
                        )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {documentsQuery.isFetchNextPageError && (
              <div
                role="alert"
                className="border-t border-red-100 bg-red-50 px-5 py-3 text-sm text-red-700"
              >
                Could not load more documents:{" "}
                {getErrorMessage(documentsQuery.error)}
              </div>
            )}

            {documentsQuery.hasNextPage && (
              <div className="flex justify-center border-t border-slate-100 px-5 py-4">
                <button
                  type="button"
                  onClick={() => void documentsQuery.fetchNextPage()}
                  disabled={documentsQuery.isFetchingNextPage}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {documentsQuery.isFetchingNextPage
                    ? 'Loading...'
                    : documentsQuery.isFetchNextPageError
                      ? 'Retry loading more documents'
                      : 'Load more documents'}
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
