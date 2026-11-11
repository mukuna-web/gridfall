import type { ReactNode } from 'react'

interface PanelHeaderProps {
  readonly index: string
  readonly id: string
  readonly title: string
  readonly children?: ReactNode
}

/** Numbered section head: "01  Storm map", with optional tools on the right. */
export function PanelHeader({ index, id, title, children }: PanelHeaderProps) {
  return (
    <header className="panel__head">
      <span className="panel__index num" aria-hidden="true">
        {index}
      </span>
      <h2 className="panel__title" id={id}>
        {title}
      </h2>
      {children ? <div className="panel__tools">{children}</div> : null}
    </header>
  )
}
