import { describe, expect, it } from 'vitest'
import { addQuotations } from './files'

function file(name: string, size = 1024) {
  return { name, size }
}

describe('addQuotations', () => {
  it('appends a new quotation to the chosen ones', () => {
    const result = addQuotations([file('a.pdf')], [file('b.pdf')], 10)
    expect(result.files.map((item) => item.name)).toEqual(['a.pdf', 'b.pdf'])
    expect(result.messages).toEqual([])
  })

  it('keeps the first copy of a file and says which one was skipped', () => {
    const result = addQuotations([file('a.pdf')], [file('a.pdf'), file('b.pdf')], 10)
    expect(result.files.map((item) => item.name)).toEqual(['a.pdf', 'b.pdf'])
    expect(result.messages).toEqual(['a.pdf is already added.'])
  })

  it('does not add more than the server limit', () => {
    const existing = [file('a.pdf'), file('b.pdf')]
    const result = addQuotations(existing, [file('c.pdf')], 2)
    expect(result.files).toHaveLength(2)
    expect(result.messages).toEqual(['Only 2 supplier quotations can be checked at once.'])
  })

  it('accepts any selection up to the twenty quotation limit', () => {
    const selected = Array.from({ length: 19 }, (_, index) => file(`quote-${index}.pdf`))
    const result = addQuotations(selected, [file('quote-19.pdf')], 20)

    expect(result.files).toHaveLength(20)
    expect(result.messages).toEqual([])
  })
})
