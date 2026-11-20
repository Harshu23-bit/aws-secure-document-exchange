import { describe, expect, it } from 'vitest'

describe('frontend test environment', () => {
  it('provides a browser-like DOM environment', () => {
    const element = document.createElement('div')

    expect(element).toBeInstanceOf(HTMLElement)
  })
})
