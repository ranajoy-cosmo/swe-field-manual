// Shared Typst template for SWE Field Manual books.

#let book(title: "", author: "SWE Field Manual", body) = {
  set document(title: title, author: author)
  set page(paper: "us-letter", margin: (x: 1in, y: 1in), numbering: "1")
  set text(font: "New Computer Modern", size: 11pt)
  set heading(numbering: "1.1")

  show raw.where(block: true): block.with(
    fill: luma(245),
    inset: 8pt,
    radius: 4pt,
    width: 100%,
  )
  show raw: set text(font: "DejaVu Sans Mono", size: 9.5pt)

  // Title page
  align(center + horizon)[
    #text(size: 28pt, weight: "bold")[#title]
    #v(1em)
    #text(size: 14pt)[#author]
  ]
  pagebreak()

  outline(title: "Contents", depth: 3)
  pagebreak()

  body
}
