import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
}))

vi.mock('../../../lib/apiServices', () => ({
  submissionService: {
    create: mocks.create,
  },
}))

import CreateSubmissionModal from '../CreateSubmissionModal'

const TENANT_ID = 'tenant-a'
const USER_ID = 'user-a'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

function renderModal(onClose = vi.fn()) {
  const queryClient = createTestQueryClient()

  const result = render(
    <QueryClientProvider client={queryClient}>
      <CreateSubmissionModal
        tenantId={TENANT_ID}
        userId={USER_ID}
        onClose={onClose}
      />
    </QueryClientProvider>,
  )

  return {
    ...result,
    queryClient,
    onClose,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void

  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })

  return { promise, resolve, reject }
}

describe('CreateSubmissionModal', () => {
  beforeEach(() => {
    mocks.create.mockReset()
    mocks.create.mockResolvedValue({})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the dialog and its form fields', () => {
    renderModal()

    expect(
      screen.getByRole('dialog', { name: 'Create submission' }),
    ).toBeInTheDocument()

    expect(screen.getByLabelText(/Submission title/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Description/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Create draft' }),
    ).toBeDisabled()
  })

  it('keeps submission disabled until the title contains at least three non-whitespace characters', async () => {
    const user = userEvent.setup()

    renderModal()

    const titleInput = screen.getByLabelText(/Submission title/)
    const submitButton = screen.getByRole('button', {
      name: 'Create draft',
    })

    await user.type(titleInput, '  ')
    expect(submitButton).toBeDisabled()

    await user.type(titleInput, 'a')
    expect(submitButton).toBeDisabled()

    await user.type(titleInput, 'bc')
    expect(submitButton).toBeEnabled()
  })

  it('displays the title and description character counters', async () => {
    const user = userEvent.setup()

    renderModal()

    await user.type(screen.getByLabelText(/Submission title/), 'Example')
    await user.type(screen.getByLabelText(/Description/), 'Test description')

    expect(screen.getByText('7/200')).toBeInTheDocument()
    expect(screen.getByText('16/2000')).toBeInTheDocument()
  })

  it('creates a submission using trimmed values and the correct tenant', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.type(
      screen.getByLabelText(/Submission title/),
      '  Security assessment  ',
    )

    await user.type(
      screen.getByLabelText(/Description/),
      '  Initial security review  ',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(TENANT_ID, {
        title: 'Security assessment',
        description: 'Initial security review',
      })
    })

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it('omits the description when it contains only whitespace', async () => {
    const user = userEvent.setup()

    renderModal()

    await user.type(
      screen.getByLabelText(/Submission title/),
      'New submission',
    )

    await user.type(
      screen.getByLabelText(/Description/),
      '     ',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(TENANT_ID, {
        title: 'New submission',
      })
    })
  })

  it('invalidates the correct user and tenant submission cache after success', async () => {
    const user = userEvent.setup()
    const { queryClient } = renderModal()

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Cache invalidation test',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['submissions', USER_ID, TENANT_ID],
      })
    })
  })

  it('displays an API error and keeps the modal open', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    mocks.create.mockRejectedValueOnce(
      new Error('Submission service unavailable'),
    )

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Failure test',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Submission service unavailable',
    )

    expect(onClose).not.toHaveBeenCalled()
  })

  it('handles structured FastAPI validation errors safely', async () => {
    const user = userEvent.setup()

    renderModal()

    const validationError = Object.assign(
      new Error('Request failed with status code 422'),
      {
        isAxiosError: true,
        response: {
          data: {
            detail: [
              {
                loc: ['body', 'title'],
                msg: 'String should have at least 3 characters',
                type: 'string_too_short',
              },
            ],
          },
        },
      },
    )

    mocks.create.mockRejectedValueOnce(validationError)

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Validation error test',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Unable to create submission. Please try again.',
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('allows the user to retry after a failed creation', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    mocks.create
      .mockRejectedValueOnce(new Error('Temporary failure'))
      .mockResolvedValueOnce({})

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Retry test',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Temporary failure',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledTimes(2)
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it('disables form controls and dismissal while creation is pending', async () => {
    const user = userEvent.setup()
    const request = deferred<unknown>()

    mocks.create.mockReturnValueOnce(request.promise)

    const { onClose } = renderModal()

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Pending test',
    )

    await user.click(
      screen.getByRole('button', { name: 'Create draft' }),
    )

    expect(await screen.findByRole('button', { name: /Creating/ })).toBeDisabled()

    expect(screen.getByLabelText(/Submission title/)).toBeDisabled()
    expect(screen.getByLabelText(/Description/)).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close dialog' })).toBeDisabled()

    expect(onClose).not.toHaveBeenCalled()

    await act(async () => {
      request.resolve({})
      await request.promise
    })

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it('prevents duplicate API requests while creation is pending', async () => {
    const request = deferred<unknown>()
    mocks.create.mockReturnValueOnce(request.promise)

    const { onClose } = renderModal()
    const user = userEvent.setup()

    await user.type(
      screen.getByLabelText(/Submission title/),
      'Duplicate submission test',
    )

    const submitButton = screen.getByRole('button', {
      name: 'Create draft',
    })

    expect(submitButton).toBeEnabled()

    await user.click(submitButton)

    expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(
      screen.getByRole('button', { name: 'Creating...' }),
    ).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Creating...' }))

    expect(mocks.create).toHaveBeenCalledTimes(1)

    await act(async () => {
      request.resolve({})
      await request.promise
    })

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it('closes when Cancel is clicked without creating a submission', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('closes when the close button is clicked without creating a submission', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: 'Close dialog' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mocks.create).not.toHaveBeenCalled()
  })
})
