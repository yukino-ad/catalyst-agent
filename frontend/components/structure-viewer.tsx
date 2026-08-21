"use client";

import { BoxIcon, CameraIcon, RotateCcwIcon, TagIcon, ViewIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { StructureData } from "@/lib/catalyst-api";
import { Button } from "@/components/ui/button";

const COLORS: Record<string, number> = {
  Al: 0xb8c4d4,
  Co: 0x3b82f6,
  Cr: 0x16a34a,
  Cu: 0xd97706,
  Fe: 0xdc2626,
  Mn: 0x8b5cf6,
  Ni: 0x10b981,
  Ag: 0xbfc5cc,
  Au: 0xeab308,
  Pd: 0x64748b,
  Pt: 0x94a3b8,
  C: 0x222222,
  O: 0xef4444,
  H: 0xf8fafc,
  N: 0x2563eb,
  S: 0xeab308,
};

type ViewDirection = "iso" | "x" | "y" | "z";

export function StructureViewer({ structure }: { structure: StructureData }) {
  const host = useRef<HTMLDivElement>(null);
  const controller = useRef<{
    view: (direction: ViewDirection) => void;
    screenshot: () => void;
    setCell: (visible: boolean) => void;
    setLabels: (visible: boolean) => void;
  } | null>(null);
  const [showCell, setShowCell] = useState(true);
  const [showLabels, setShowLabels] = useState(false);
  const [projection, setProjection] = useState<"perspective" | "orthographic">("perspective");
  const lengths = useMemo(
    () => structure.lattice.map((vector) => Math.hypot(...vector)),
    [structure.lattice],
  );

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const width = element.clientWidth || 900;
    const height = element.clientHeight || 560;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf5f7fa);
    const perspective = new THREE.PerspectiveCamera(42, width / height, 0.1, 2000);
    const orthoSize = 22;
    const orthographic = new THREE.OrthographicCamera(
      (-orthoSize * width) / height,
      (orthoSize * width) / height,
      orthoSize,
      -orthoSize,
      0.1,
      2000,
    );
    let camera: THREE.Camera = projection === "orthographic" ? orthographic : perspective;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    element.replaceChildren(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 2.6));
    const directional = new THREE.DirectionalLight(0xffffff, 2.1);
    directional.position.set(20, 30, 40);
    scene.add(directional);

    const center = new THREE.Vector3();
    structure.atoms.forEach((atom) =>
      center.add(new THREE.Vector3(atom.position[0], atom.position[1], atom.position[2])),
    );
    center.divideScalar(Math.max(1, structure.atoms.length));
    const group = new THREE.Group();
    group.position.copy(center).multiplyScalar(-1);
    scene.add(group);
    const labels = new THREE.Group();
    group.add(labels);

    structure.atoms.forEach((atom) => {
      const geometry = new THREE.SphereGeometry(atom.movable ? 0.62 : 0.52, 24, 16);
      const material = new THREE.MeshStandardMaterial({
        color: COLORS[atom.element] ?? 0x6b7280,
        roughness: 0.38,
        metalness: ["C", "O", "H", "N", "S"].includes(atom.element) ? 0.05 : 0.45,
        transparent: !atom.movable,
        opacity: atom.movable ? 1 : 0.65,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(atom.position[0], atom.position[1], atom.position[2]);
      group.add(mesh);
      const sprite = makeLabel(`${atom.element}${atom.index}`);
      sprite.position.copy(mesh.position).add(new THREE.Vector3(0, 0.85, 0));
      labels.add(sprite);
    });
    labels.visible = showLabels;

    const [a, b, c] = structure.lattice.map(
      (vector) => new THREE.Vector3(vector[0], vector[1], vector[2]),
    );
    const corners = [
      new THREE.Vector3(),
      a,
      b,
      c,
      a.clone().add(b),
      a.clone().add(c),
      b.clone().add(c),
      a.clone().add(b).add(c),
    ];
    const vertices: THREE.Vector3[] = [];
    [
      [0, 1],
      [0, 2],
      [0, 3],
      [1, 4],
      [1, 5],
      [2, 4],
      [2, 6],
      [3, 5],
      [3, 6],
      [4, 7],
      [5, 7],
      [6, 7],
    ].forEach(([x, y]) => vertices.push(corners[x], corners[y]));
    const cell = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(vertices),
      new THREE.LineBasicMaterial({ color: 0x475569, opacity: 0.75, transparent: true }),
    );
    cell.visible = showCell;
    group.add(cell);

    let controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const radius = Math.max(
      ...structure.atoms.map((atom) =>
        new THREE.Vector3(atom.position[0], atom.position[1], atom.position[2]).distanceTo(center),
      ),
      8,
    );
    const setView = (direction: ViewDirection) => {
      const positions: Record<ViewDirection, [number, number, number]> = {
        iso: [1.25, 1.15, 1.5],
        x: [2, 0, 0],
        y: [0, 2, 0],
        z: [0, 0, 2],
      };
      const [x, y, z] = positions[direction];
      camera.position.set(radius * x, radius * y, radius * z);
      camera.up.set(0, 1, 0);
      controls.target.set(0, 0, 0);
      controls.update();
    };
    controller.current = {
      view: setView,
      setCell: (visible) => {
        cell.visible = visible;
      },
      setLabels: (visible) => {
        labels.visible = visible;
      },
      screenshot: () => {
        renderer.render(scene, camera);
        const link = document.createElement("a");
        link.download = `${structure.name || "structure"}.png`;
        link.href = renderer.domElement.toDataURL("image/png");
        link.click();
      },
    };
    setView("iso");
    let frame = 0;
    const render = () => {
      controls.update();
      labels.children.forEach((child) => child.quaternion.copy(camera.quaternion));
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();
    const resize = new ResizeObserver(() => {
      const nextWidth = element.clientWidth;
      const nextHeight = element.clientHeight;
      if (!nextWidth || !nextHeight) return;
      perspective.aspect = nextWidth / nextHeight;
      perspective.updateProjectionMatrix();
      orthographic.left = (-orthoSize * nextWidth) / nextHeight;
      orthographic.right = (orthoSize * nextWidth) / nextHeight;
      orthographic.updateProjectionMatrix();
      renderer.setSize(nextWidth, nextHeight);
    });
    resize.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      renderer.dispose();
      controller.current = null;
      scene.traverse((item) => {
        if (item instanceof THREE.Mesh || item instanceof THREE.LineSegments) {
          item.geometry.dispose();
          const materials = Array.isArray(item.material) ? item.material : [item.material];
          materials.forEach((material) => material.dispose());
        }
      });
    };
  }, [projection, structure]);

  return (
    <div className="border bg-slate-50">
      <div className="flex flex-wrap items-center gap-1 border-b bg-white px-2 py-2">
        <ToolButton label="等轴视图" onClick={() => controller.current?.view("iso")}>
          <ViewIcon />
        </ToolButton>
        {(["x", "y", "z"] as ViewDirection[]).map((view) => (
          <Button
            key={view}
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => controller.current?.view(view)}
          >
            {view.toUpperCase()}
          </Button>
        ))}
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="ml-2"
          onClick={() =>
            setProjection((value) => (value === "perspective" ? "orthographic" : "perspective"))
          }
        >
          {projection === "perspective" ? "透视" : "正交"}
        </Button>
        <ToolButton
          label="显示晶胞"
          active={showCell}
          onClick={() => {
            setShowCell((value) => {
              controller.current?.setCell(!value);
              return !value;
            });
          }}
        >
          <BoxIcon />
        </ToolButton>
        <ToolButton
          label="显示原子标签"
          active={showLabels}
          onClick={() => {
            setShowLabels((value) => {
              controller.current?.setLabels(!value);
              return !value;
            });
          }}
        >
          <TagIcon />
        </ToolButton>
        <ToolButton label="重置视角" onClick={() => controller.current?.view("iso")}>
          <RotateCcwIcon />
        </ToolButton>
        <ToolButton label="下载 PNG" onClick={() => controller.current?.screenshot()}>
          <CameraIcon />
        </ToolButton>
      </div>
      <div ref={host} className="h-[56vh] min-h-[440px] w-full" />
      <div className="grid gap-3 border-t bg-white px-3 py-3 text-xs text-muted-foreground md:grid-cols-[1fr_auto]">
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {structure.elements.map((element) => (
            <span key={element} className="flex items-center gap-1">
              <i className="size-2.5 rounded-full" style={{ background: colorHex(element) }} />
              {element}
            </span>
          ))}
          <span>透明小球：固定原子</span>
          <span>实色大球：可移动原子</span>
        </div>
        <div className="text-right">
          {structure.atom_count} atoms · a/b/c ={" "}
          {lengths.map((value) => value.toFixed(3)).join(" / ")} Ang
        </div>
      </div>
    </div>
  );
}

function ToolButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      size="icon-sm"
      variant={active ? "secondary" : "ghost"}
      title={label}
      aria-label={label}
      onClick={onClick}
    >
      <span className="[&_svg]:size-4">{children}</span>
    </Button>
  );
}

function makeLabel(text: string) {
  const canvas = document.createElement("canvas");
  canvas.width = 160;
  canvas.height = 64;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "rgba(255,255,255,.88)";
    context.fillRect(0, 0, 160, 64);
    context.fillStyle = "#172033";
    context.font = "bold 28px Arial";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, 80, 32);
  }
  const material = new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas),
    transparent: true,
    depthTest: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(2, 0.8, 1);
  return sprite;
}

function colorHex(element: string) {
  return `#${(COLORS[element] ?? 0x6b7280).toString(16).padStart(6, "0")}`;
}
