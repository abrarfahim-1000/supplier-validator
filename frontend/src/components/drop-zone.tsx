import type { ReactNode } from 'react'
import { useDropzone } from 'react-dropzone'
import type { Accept, FileRejection } from 'react-dropzone'

export interface DropZoneProps {
  accept?: Accept
  multiple?: boolean
  maxFiles?: number
  maxSize?: number
  disabled?: boolean
  icon: ReactNode
  primary: string
  secondary: string
  onFiles: (files: File[]) => void
  onReject: (rejections: FileRejection[]) => void
}

/**
 * The drop target and the click target are the same visible area. react-dropzone owns the
 * drop and accept rules; the button owns the click and the keyboard.
 */
export function DropZone({
  accept,
  multiple = false,
  maxFiles,
  maxSize,
  disabled = false,
  icon,
  primary,
  secondary,
  onFiles,
  onReject,
}: DropZoneProps) {
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    accept,
    multiple,
    maxFiles: multiple ? maxFiles : 1,
    maxSize,
    disabled,
    noClick: true,
    noKeyboard: true,
    onDrop: onFiles,
    onDropRejected: onReject,
  })

  return (
    <div {...getRootProps({ tabIndex: -1 })}>
      <input {...getInputProps()} />
      <button
        type="button"
        className="dropzone"
        data-active={isDragActive}
        disabled={disabled}
        onClick={open}
      >
        <span className="dropzone__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="dropzone__text">
          <span className="dropzone__primary">
            {isDragActive ? 'Release to add' : primary}
          </span>
          <span className="dropzone__secondary">{secondary}</span>
        </span>
      </button>
    </div>
  )
}
