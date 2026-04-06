# Fractal Family for Blender

[![Blender Extensions](https://img.shields.io/badge/Extensions-Fractal_Family-blue?logo=blender)](https://extensions.blender.org/add-ons/fractal-family/) ![Blender Version](https://img.shields.io/badge/Blender-4.2%2B-orange) ![License](https://img.shields.io/badge/License-GPL-green)

**Fractal Family** is a Blender extension that allows you to easily create fractal curves using complex integer lattices. Based on [Jeffrey Ventrella's research](http://www.fractalcurves.com/familytree/), it enables the exploration of the "family tree" of fractal curves through recursive substitution on Gaussian (square) or Eisenstein (triangular) grids.

## Usage Guide

> **Tip**: Use **Top View** (Numpad 7) when using this add-on for better experience.

The panel is located in **3D Viewport** -> **Sidebar (N)** -> **Edit** tab -> **Fractal Family**.

### 1. Configuration & Preview
- **Preset**: Start quickly with built-in classics like *Koch Curve*, *Dragon Curve*, or *Gosper Island*.
- **Domain**: Choose the underlying grid structure.
    - **Gaussian (G)**: Square grid ($a + bi$).
    - **Eisenstein (E)**: Triangular/Hexagonal grid ($a + b\omega$).
- **Level**: Depth of recursion (1-20).
- **Spline Type**: **Poly** (linear segments) or **Smooth** (Bezier splines).
- **Initiator Curve**: (Optional) Use a custom curve object as the base shape (axiom) instead of a straight line.
    - **Tip**: Use a regular triangle curve with the **Koch Curve** preset to create a **Koch Snowflake**. Since the generation direction is determined by the spline's vertex order, it is recommended to enable the **Reverse** switch (next to the **Initiator Curve** selector) to ensure the fractal grows **outward**.
    - **Tip**: Use a regular hexagon curve with **Gosper Island** preset to create a closed Gosper Island.
- **Show Preview**: Real-time preview to see the shape when editing the generator.

### 2. Designing Generators
Customize the fractal's "DNA" by editing the generator items. The generator is a sequence of Complex Integers along with a pair of Transform Flags.
- **A / B**: Coordinates of the complex integer.
- **Transform Flags**:
    - **R (Reverse)**: Reverses the pattern for this segment.
    - **M (Mirror)**: Mirrors the pattern for this segment.

### 3. Generation Modes
- **Create Last Level**: Generates the final curve at the specified level.
- **Create Each Level**: Generates separate objects for every level from 0 to N.
- **Create Curve with Shape Keys**: Creates a single object capable of morphing.
    - The addon automatically configures the **Shape Keys** (disables *Relative* mode). You can simply animate the **Evaluation Time** property that appears below the button to grow the fractal.

## ⚠️ Limitations
- Supports **Edge Replacement** fractals on complex integer lattices X-Y plane. Does not support L-Systems or **Node Replacement** fractals (e.g. standard Hilbert Curve) directly.