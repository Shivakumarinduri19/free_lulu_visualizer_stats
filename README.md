# Dynamic World LULC Visualizer & Change Detection
credits : google dataset and google earth engine api 

An interactive geospatial web platform for near-real-time 10-meter Land Use and Land Cover (LULC) visualization and multi-temporal change detection, powered by Google Earth Engine (Dynamic World V1) and FastAPI.

## Key Features

- **Google Dynamic World V1 (10m Resolution)**:
  - Global land cover classifications derived from Sentinel-2 L2A satellite imagery.
  - 9 discrete classes: Water, Trees, Grass, Flooded Vegetation, Crops, Shrub & Scrub, Built Area, Bare Ground, and Snow & Ice.
- **Multi-Temporal Change Detection & Split Panel**:
  - Compare two different time periods (e.g. 2018 vs 2024) across the exact same study area.
  - Interactive draggable vertical swipe divider (`⇄`) for before-and-after visual inspection.
  - Automated delta calculations: Net area changes ($\pm$ hectares and $\pm$%), top expanding class, and top shrinking class.
- **Geolocation ("Locate Me")**:
  - Detects user browser coordinates and creates an instant 2×2 km or 5×5 km bounding box for local area analysis.
- **Dynamic Zonal Statistics**:
  - Real-time reduction inside user-drawn polygons or rectangles using Earth Engine's `pixelArea()`.
  - Calculates area in hectares, square kilometers, and percentage distribution.
- **Glassmorphic User Interface**:
  - Fullscreen dark mode interface with frosted glass floating panels (`backdrop-filter: blur(24px)`).
  - Collapsible analytics drawer for full map view.
  - Donut and grouped horizontal bar charts powered by Chart.js.
- **Data Export**:
  - Download zonal statistics and transition matrix data as CSV.

## Project Structure

```
├── backend.py                         # FastAPI service & Earth Engine processing
├── dynamic_world_lulc_visualizer.html # Interactive frontend (Leaflet + Chart.js)
├── index.html                         # Static entry point
├── requirements.txt                   # Python dependencies
├── .gitignore                         # Excludes service accounts, keys, and environments
└── README.md                          # Documentation
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Shivakumarinduri19/free_lulu_visualizer_stats.git
cd free_lulu_visualizer_stats
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Google Earth Engine Setup

This project requires authentication with Google Earth Engine using either of the following approaches:

### Method 1: Service Account Key (Recommended)
Place your Google Cloud Service Account JSON key in the root directory named `service_account.json`:
```
service_account.json
```
The backend automatically detects and initializes using this file.
*(Note: `service_account.json` is listed in `.gitignore` and is never tracked by git).*

### Method 2: Local CLI Authentication
Authenticate your machine via Earth Engine CLI:
```bash
earthengine authenticate
```
Specify your Google Cloud project via a `.env` file or environment variable:
```env
GEE_PROJECT=your-gcp-project-id
```

## Running the Application

Launch the local development server:
```bash
uvicorn backend:app --reload --port 8000
```

Access the application in your browser:
- Web App: `http://localhost:8000/`
- API Health Check: `http://localhost:8000/api/health`
- Interactive API Docs: `http://localhost:8000/docs`

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
