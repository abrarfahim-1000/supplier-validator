export interface FileLike {
  name: string
  size: number
}

export interface AddQuotationsResult<T extends FileLike> {
  files: T[]
  /** One line per file that was not added, written for the person who selected it. */
  messages: string[]
}

function identity(file: FileLike): string {
  return `${file.name}:${file.size}`
}

/**
 * Adds newly selected quotations to the ones already chosen, keeping the first copy of each
 * file. The backend hashes the content as well; this only catches the obvious repeat before
 * an upload is attempted.
 */
export function addQuotations<T extends FileLike>(
  existing: readonly T[],
  incoming: readonly T[],
  max: number,
): AddQuotationsResult<T> {
  const files = [...existing]
  const seen = new Set(files.map(identity))
  const messages: string[] = []

  for (const file of incoming) {
    if (seen.has(identity(file))) {
      messages.push(`${file.name} is already added.`)
      continue
    }
    if (files.length >= max) {
      messages.push(`Only ${max} supplier quotations can be checked at once.`)
      continue
    }
    seen.add(identity(file))
    files.push(file)
  }

  return { files, messages }
}
