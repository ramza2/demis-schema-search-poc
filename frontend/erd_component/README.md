# DEMIS ERD Component

Streamlit custom component used by `ERD Explorer`.

## Runtime architecture

- `@xyflow/react`: interactive pan / zoom / selection / MiniMap
- `elkjs`: layered automatic layout and orthogonal edge routing
- `streamlit-component-lib`: bridge between Streamlit and the React component

The component receives the already source-scoped ERD JSON from Python. ELK runs in the browser to calculate node positions and edge bend points. React Flow renders those bend points through a custom orthogonal edge, so relationship lines avoid table boxes instead of using the previous grid/straight-line renderer.

The compiled `dist/` directory is created inside the frontend Docker multi-stage build and copied into the Python runtime image. The running military/offline image does not require npm, a CDN, or an external network connection.

## Display policy

- Full ERD: automatic layout, orthogonal routing, FK labels hidden, Focus Table neighborhoods highlighted.
- Neighborhood ERD: only bounded hops are supplied and FK labels are shown.
- Category ERD: only tables assigned to the selected Category are supplied.
- Relationship Details remain rendered by Streamlit below the graph.

## Dependency licenses

- `@xyflow/react`: MIT
- `elkjs`: EPL-2.0 OR GPL-3.0-or-later (use and record the EPL-2.0 option in delivery OSS notices)
- `streamlit-component-lib`: Apache-2.0

Final delivery should include these packages in the OSS/SBOM inventory.
