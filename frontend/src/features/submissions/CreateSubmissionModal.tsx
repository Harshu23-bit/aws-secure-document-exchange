import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { AlertCircle, FilePlus2, Loader2, X } from 'lucide-react'
import { submissionService } from '../../lib/apiServices'
import type { SubmissionCreateRequest } from '../../types/api'

interface CreateSubmissionModalProps {
  tenantId: string
  userId: string
  onClose: () => void
}

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError<{ detail?: unknown }>(error)) {
    const detail = error.response?.data?.detail

    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detail
    }

    return 'Unable to create submission. Please try again.'
  }

  return error instanceof Error
    ? error.message
    : 'An unexpected error occurred.'
}

export default function CreateSubmissionModal({
  tenantId,
  userId,
  onClose,
}: CreateSubmissionModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const submissionInFlightRef = useRef(false)

  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: (request: SubmissionCreateRequest) =>
      submissionService.create(tenantId, request),

    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['submissions', userId, tenantId],
      })
      onClose()
    },

    onSettled: () => {
      submissionInFlightRef.current = false
    },
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const cleanTitle = title.trim()
    const cleanDescription = description.trim()

    if (cleanTitle.length < 3 || cleanTitle.length > 200) {
      return
    }

    if (cleanDescription.length > 2000) {
      return
    }

    if (submissionInFlightRef.current) {
      return
    }

    submissionInFlightRef.current = true

    createMutation.mutate({
      title: cleanTitle,
      ...(cleanDescription ? { description: cleanDescription } : {}),
    })
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/50 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !createMutation.isPending) {
          onClose()
        }
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-submission-title"
        className="w-full max-w-lg rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-600">
              <FilePlus2 size={21} />
            </div>

            <div>
              <h2
                id="create-submission-title"
                className="font-semibold text-slate-900"
              >
                Create submission
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Create a new draft in this workspace.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
            aria-label="Close dialog"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X size={19} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 p-6">
          <div>
            <label
              htmlFor="submission-title"
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Submission title <span className="text-red-500">*</span>
            </label>

            <input
              id="submission-title"
              type="text"
              required
              minLength={3}
              maxLength={200}
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Enter a submission title"
              disabled={createMutation.isPending}
              className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
            />

            <p className="mt-1 text-right text-xs text-slate-400">
              {title.length}/200
            </p>
          </div>

          <div>
            <label
              htmlFor="submission-description"
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Description <span className="text-slate-400">(optional)</span>
            </label>

            <textarea
              id="submission-description"
              rows={5}
              maxLength={2000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Provide some context about this submission..."
              disabled={createMutation.isPending}
              className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
            />

            <p className="mt-1 text-right text-xs text-slate-400">
              {description.length}/2000
            </p>
          </div>

          {createMutation.isError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              <AlertCircle size={17} className="mt-0.5 shrink-0" />
              <p>{getErrorMessage(createMutation.error)}</p>
            </div>
          )}

          <div className="flex justify-end gap-3 border-t border-slate-100 pt-5">
            <button
              type="button"
              onClick={onClose}
              disabled={createMutation.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>

            <button
              type="submit"
              disabled={
                createMutation.isPending ||
                title.trim().length < 3 ||
                title.trim().length > 200 ||
                description.trim().length > 2000
              }
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Creating...
                </>
              ) : (
                'Create draft'
              )}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
