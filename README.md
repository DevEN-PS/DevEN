# ⚡ DevEN - Develop Electric Network

**Next-Generation Power System Analysis & Visualization**

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/DevEN-PS/DevEN/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Downloads](https://img.shields.io/badge/downloads-latest-blue)](https://github.com/DevEN-PS/DevEN/releases)

**DevEN** (Develop Electric Network) is a cutting-edge, highly interactive power system simulation and geographic visualization software. Built for modern engineers, researchers, and planners, DevEN seamlessly blends rigorous electrical analysis (Load Flow and Short Circuit studies) with a stunning, interactive geographical interface powered by OpenStreetMap.

---

## 📸 Screenshots

<div align="center">
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_1.png?raw=true" alt="DevEN Dashboard" width="800">
  <br>
  <em>Main Dashboard - Dark Mode Interface</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_2.png?raw=true" alt="DevEN SLD Editor" width="800">
  <br>
  <em>Single Line Diagram Editor with Grid Components</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_3.png?raw=true" alt="DevEN GIS Map" width="800">
  <br>
  <em>GIS Map Viewer with OpenStreetMap Integration</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_4.png?raw=true" alt="DevEN Analysis Results" width="800">
  <br>
  <em>Load Flow Analysis Results Visualization</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_5.png?raw=true" alt="DevEN Component Properties" width="800">
  <br>
  <em>Component Properties and Configuration Panel</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_6.png?raw=true" alt="DevEN Short Circuit Analysis" width="800">
  <br>
  <em>Short Circuit Study Results</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_7.png?raw=true" alt="DevEN Report Export" width="800">
  <br>
  <em>PDF/Excel Report Generation</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_8.png?raw=true" alt="DevEN Project Management" width="800">
  <br>
  <em>Project Management and File Handling</em>
  <br><br>
  <img src="https://github.com/DevEN-PS/DevEN/blob/main/images/DevEN_9.png?raw=true" alt="DevEN Settings" width="800">
  <br>
  <em>Configuration and Settings Panel</em>
</div>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🎯 Why DevEN](#-why-deven)
- [🚀 Quick Start](#-quick-start)
- [📦 Installation](#-installation)
- [📦 Dependencies](#-dependencies)
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
- **Convergence Monitoring** - Automatic tracking and reporting
- **Customizable Parameters** - Slack bus selection, tolerance settings

### 2. Interactive SLD Editor
- **Drag-and-Drop** - Build grids intuitively with mouse
- **Deep Customization** - Node radii, colors, line weights, text rotation
- **Smart Navigation** - Shift-click to locate components
- **Real-time Editing** - Changes reflect immediately
- **Component Library** - Buses, Generators, Loads, Transmission Lines, Transformers
- **Auto-Connection** - Intelligent snapping and routing

### 3. GIS Mapping Integration
- **Live Map Viewer** - Powered by OpenStreetMap
- **Visual Syncing** - Results overlay on geographical map
- **Geographic Customization** - Grid visibility, scales, colors, zoom thresholds
- **Coordinate Support** - Latitude/Longitude or address geocoding
- **Multiple Layers** - Toggle visibility of different grid elements
- **Real-time Updates** - Results overlay instantly after analysis

### 4. Project Management
- **Database as Code** - Save as `.py` files (version control friendly)
- **Complete Persistence** - All visual settings, coordinates, and UI tweaks preserved
- **Export/Import** - Share projects easily
- **Auto-Save** - Never lose your work
- **Backup Recovery** - Automatic backup creation

### 5. Modern UI/UX
- **Dark Mode** - Built with CustomTkinter
- **Responsive Design** - Adapts to any screen size
- **Keyboard Shortcuts** - Boost productivity
- **One-Click Updates** - Auto-check for new releases
- **Customizable Themes** - Dark/Light mode toggle
- **Intuitive Layout** - Easy to navigate and use

### 6. Reporting & Export
- **PDF Reports** - Professional analysis reports with branding
- **Excel Export** - Raw data for further analysis
- **Image Export** - PNG/SVG of SLD and Maps
- **Custom Templates** - Brand your reports
- **CSV Export** - Component data and results
- **Batch Export** - Export multiple formats at once

---

## 🎯 Why DevEN?

| **Traditional Tools** | **DevEN** |
|----------------------|-----------|
| Outdated interfaces | Modern, sleek UI |
| Abstract results | Real-world GIS visualization |
| Complex workflows | One-click analysis |
| Static reports | Interactive visualizations |
| Hard to share | Version control friendly |
| Expensive licenses | Open-source and free |
| Limited customization | Fully customizable |

**Perfect for:**
- 🔌 **Grid Planners** - Visualize new generator impacts
- 📊 **Consultants** - Create stunning visual reports for clients  
- 🔬 **Researchers** - Flexible and fast simulation tool
- 🎓 **Educators** - Teach power systems with visual aids
- 🏭 **Utility Engineers** - Daily grid operations and planning

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- pip package manager
- Git (optional)

### Installation

```bash
# Clone the repository
git clone https://github.com/DevEN-PS/DevEN.git
cd DevEN

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run DevEN
python app.py
