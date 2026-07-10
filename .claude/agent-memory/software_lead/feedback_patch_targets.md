---
name: Patch targets must use module-local imports
description: When replacing a cv2/external call with a stdlib/scipy equivalent, import the replacement directly into the module so tests can patch photo_workflow.<module>.<name>
type: feedback
---

Always import replacements (e.g., `from scipy.ndimage import laplace`) directly into the module, not via the library namespace. This lets tests patch `photo_workflow.sharpness.laplace` rather than `cv2.Laplacian` or `scipy.ndimage.laplace`.

**Why:** Patching the symbol in the module's own namespace is the correct unittest.mock pattern. Patching the source library namespace only works when the module does `import cv2` and calls `cv2.Laplacian` — not when using a direct import.

**How to apply:** Any time a function in a photo_workflow module calls an external function, that function should be imported directly at the top of the module (e.g., `from scipy.ndimage import laplace`), not accessed through its parent package. Tests then patch `photo_workflow.<module>.<symbol>`.
