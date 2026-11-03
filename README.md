# cutlab-fusion-addins

Python add-ins for Autodesk Fusion, written by CutLab (Tallinn, Estonia) with Claude Code.

| Add-in | What it does |
|---|---|
| CabinetGenerator | Sheet-material carcasses with through finger joints for 3-axis CNC, screw pilots in the tabs, back panel in grooves. |
| UltraboxRejs | REJS Ultrabox drawer boxes: metal sides, panels with drilling, cabinet drilling for the runners. |
| FacadeGenerator | Fronts with Blum CLIP top BLUMOTION hinge drilling (cup and dowels), edge banding options, mounting plate drilling. |
| BoxGenerator | Boxes with Lamello Cabineo 8 pockets, tab joints option, removable magnetic back. |
| CabineoSeam | Adds Cabineo 8 pockets and pilots to a seam between two faces. |

Each folder has its own `README.md` and a `.manifest` for Fusion's Add-Ins dialog.

## Installation

Copy (or symlink) the folder you need into Fusion's add-ins directory, then run it from Utilities → Add-Ins. Details are in each folder's README.

## Important notes

- **Dimensions and machining patterns come from public manufacturer catalogues and technical sheets** (REJS, Blum, Lamello). They are included for convenience. The MIT licence covers the code written by CutLab, not the manufacturers' data. Check each value against the catalogue of the product you actually buy before cutting.
- Blum, REJS, Lamello, Cabineo, GTV, Autodesk and Fusion are trademarks of their owners. CutLab is not affiliated with any of them.
- The software is provided as is. Test on scrap first.
