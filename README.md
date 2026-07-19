# ⚡ DevEN - Develop Electric Network

**Next-Generation Power System Analysis & Visualization**

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/yourusername/deven/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Downloads](https://img.shields.io/badge/downloads-latest-blue)](https://github.com/yourusername/deven/releases)

**DevEN** (Develop Electric Network) is a cutting-edge, highly interactive power system simulation and geographic visualization software. Built for modern engineers, researchers, and planners, DevEN seamlessly blends rigorous electrical analysis (Load Flow and Short Circuit studies) with a stunning, interactive geographical interface.

<p align="center">
  <img src="screenshots/dashboard.png" alt="DevEN Dashboard" width="800">
</p>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🎯 Why DevEN](#-why-deven)
- [📸 Screenshots](#-screenshots)
- [🚀 Quick Start](#-quick-start)
- [📦 Installation](#-installation)
- [💻 Usage Guide](#-usage-guide)
- [⚡ Analysis Features](#-analysis-features)
- [🗺️ GIS Mapping](#️-gis-mapping)
- [📊 Export & Reporting](#-export--reporting)
- [🔧 Configuration](#-configuration)
- [🛠️ Tech Stack](#️-tech-stack)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [🙏 Acknowledgments](#-acknowledgments)
- [📞 Support](#-support)

---

## ✨ Features

### 1. Advanced Power System Analysis
- **Load Flow Analysis (LFA)** - Newton-Raphson & Gauss-Seidel solvers
- **Short Circuit Studies (SCS)** - Symmetrical & unsymmetrical fault calculations
- **Real-time Results** - Instant visualization on SLD and Map
- **Multiple Bus Systems** - Support for up to 1000+ buses

### 2. Interactive SLD Editor
- **Drag-and-Drop** - Build grids intuitively
- **Deep Customization** - Node radii, colors, line weights, text rotation
- **Smart Navigation** - Shift-click to locate components
- **Real-time Editing** - Changes reflect immediately

### 3. GIS Mapping Integration
- **Live Map Viewer** - Powered by OpenStreetMap/Tile providers
- **Visual Syncing** - Results overlay on geographical map
- **Geographic Customization** - Grid visibility, scales, colors, zoom thresholds
- **Coordinate Support** - Latitude/Longitude or address geocoding

### 4. Project Management
- **Database as Code** - Save as `.py` files (version control friendly)
- **Complete Persistence** - All visual settings, coordinates, and UI tweaks preserved
- **Export/Import** - Share projects easily

### 5. Modern UI/UX
- **Dark Mode** - Built with CustomTkinter
- **Responsive Design** - Adapts to any screen size
- **Keyboard Shortcuts** - Boost productivity
- **One-Click Updates** - Auto-check for new releases

### 6. Reporting & Export
- **PDF Reports** - Professional analysis reports
- **Excel Export** - Raw data for further analysis
- **Image Export** - PNG/SVG of SLD and Maps
- **Custom Templates** - Brand your reports

---

## 🎯 Why DevEN?

| **Traditional Tools** | **DevEN** |
|----------------------|-----------|
| Outdated interfaces | Modern, sleek UI |
| Abstract results | Real-world GIS visualization |
| Complex workflows | One-click analysis |
| Static reports | Interactive visualizations |
| Hard to share | Version control friendly |

**Perfect for:**
- 🔌 **Grid Planners** - Visualize new generator impacts
- 📊 **Consultants** - Create stunning visual reports for clients  
- 🔬 **Researchers** - Flexible and fast simulation tool
- 🎓 **Educators** - Teach power systems with visual aids
- 🏭 **Utility Engineers** - Daily grid operations and planning

---

## 📸 Screenshots

<p align="center">
  <img src="screenshots/sld_editor.png" alt="SLD Editor" width="800">
  <br>
  <em>Single Line Diagram Editor with live analysis results</em>
</p>

<p align="center">
  <img src="screenshots/map_viewer.png" alt="GIS Map Viewer" width="800">
  <br>
  <em>Geographic visualization with power flow overlays</em>
</p>

<p align="center">
  <img src="screenshots/analysis_results.png" alt="Analysis Results" width="800">
  <br>
  <em>Detailed analysis results and reporting</em>
</p>

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- pip package manager
- Git (optional)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/deven.git
cd deven

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run DevEN
python main.py
