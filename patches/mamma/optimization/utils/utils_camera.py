import os
import platform
if platform.system() != "Windows":
    os.environ['PYOPENGL_PLATFORM'] = 'egl'
import numpy as np
import pyrender
import trimesh
import cv2

def to_homogeneous(points):
    return np.hstack((points, np.ones((points.shape[0], 1))))


def w2c(points3d, extrinsics):
    return (extrinsics @ to_homogeneous(points3d).T)[:3,].T

def project_points(points3d, intrinsics, extrinsics):
    points3d_h = to_homogeneous(points3d)
    points2d_h = intrinsics@((extrinsics @ points3d_h.T)[:3,])
    points2d = (points2d_h[:2,] / points2d_h[2:,]).T
    return points2d


def project_points_np_tensor(points3d, intrinsics, extrinsics):
    points_3d_h = np.concatenate([points3d, np.ones((points3d.shape[0], points3d.shape[1], 1))], axis=-1)
    points2d_h = np.einsum('pk,jkl->jlp', intrinsics , np.einsum('jk,ilk->ijl', extrinsics, points_3d_h)[:, :3, :])
    points2d = points2d_h[..., :2] / points2d_h[..., 2:]
    return points2d


def is_bbx_overlap(bbx1, bbx2):
    min_x1, min_y1, max_x1, max_y1 = bbx1
    min_x2, min_y2, max_x2, max_y2 = bbx2

    if max_x1 < min_x2 or max_x2 < min_x1:
        return False

    if max_y1 < min_y2 or max_y2 < min_y1:
        return False

    return True


def get_colors():
    colors = {
        'pink': np.array([197, 27, 125]),  # L lower leg
        'light_pink': np.array([233, 163, 201]),  # L upper leg
        'light_green': np.array([161, 215, 106]),  # L lower arm
        'green': np.array([77, 146, 33]),  # L upper arm
        'red': np.array([215, 48, 39]),  # head
        'light_red': np.array([252, 146, 114]),  # head
        'light_orange': np.array([252, 141, 89]),  # chest
        'purple': np.array([118, 42, 131]),  # R lower leg
        'light_purple': np.array([175, 141, 195]),  # R upper
        'light_blue': np.array([145, 191, 219]),  # R lower arm
        'blue': np.array([69, 170, 255]),  # R upper arm
        'gray': np.array([130, 130, 130]),  #
        'white': np.array([255, 255, 255]),  #
        'pinkish': np.array([204, 77, 77]),
    }
    return colors


def get_projected_points(smplx_out, cam_metadata, batch_size):
    pts2d_gt_np = []
    for frame_n in range(batch_size):
        extrinsics = cam_metadata['cam_ext']
        intrinsics = cam_metadata['cam_int']
        pts3d = smplx_out.vertices[frame_n,].cpu().detach().numpy()
        points2d_proj = project_points(pts3d, intrinsics, extrinsics)
        pts2d_gt_np.append(points2d_proj)
    pts2d_gt_np = np.stack(pts2d_gt_np, axis=0)
    return pts2d_gt_np

def create_raymond_lights():
    thetas = np.pi * np.array([1.0 / 6.0, 1.0 / 6.0, 1.0 / 6.0])
    phis = np.pi * np.array([0.0, 2.0 / 3.0, 4.0 / 3.0])

    nodes = []

    for phi, theta in zip(phis, thetas):
        xp = np.sin(theta) * np.cos(phi)
        yp = np.sin(theta) * np.sin(phi)
        zp = -np.cos(theta)

        z = np.array([xp, yp, zp])
        z = z / np.linalg.norm(z)
        x = np.array([-z[1], z[0], 0.0])
        if np.linalg.norm(x) == 0:
            x = np.array([1.0, 0.0, 0.0])
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)

        matrix = np.eye(4)
        matrix[:3,:3] = np.c_[x,y,z]
        nodes.append(pyrender.Node(
            light=pyrender.DirectionalLight(color=np.ones(3), intensity=1.),
            matrix=matrix
        ))

    return nodes

class RenderCamera:
    def __init__(self, smplx_faces):
        self.camera = None
        self.camera_node = None
        self.renderer = None
        self.light_nodes = None
        self.material = None
        self.scene = pyrender.Scene(bg_color=[0, 0, 0, 0])
        self.faces = smplx_faces
        self.mesh_nodes = {}

        light_nodes = create_raymond_lights()
        for node in light_nodes:
            self.scene.add_node(node)

    def add_camera(self, camera_intrinsics, name="cam"):
        self.camera = pyrender.IntrinsicsCamera(
            fx=camera_intrinsics[0, 0],
            fy=camera_intrinsics[1, 1],
            cx=camera_intrinsics[0, 2],
            cy=camera_intrinsics[1, 2]
        )
        opengl_camera = np.eye(4)
        opengl_camera[1, 1] = -1
        opengl_camera[2, 2] = -1
        self.camera_node = self.scene.add(self.camera, pose=opengl_camera)


    def add_mesh(self, smplx_out, frame_n, cam_extrinsics, camera_intrinsics, mesh_name="mesh", color_name="light_blue"):
        alpha = 1.0
        mesh_color=get_colors()[color_name]
        mesh_color = mesh_color[::-1]
        material = pyrender.MetallicRoughnessMaterial(
                metallicFactor=0.2,
                alphaMode='OPAQUE',
                roughnessFactor=0.5,
                baseColorFactor=(mesh_color[0] / 255., mesh_color[1] / 255., mesh_color[2] / 255., alpha))

        vertices = smplx_out.vertices[frame_n,].cpu().detach().numpy()

        points2d_proj = project_points(vertices, camera_intrinsics, cam_extrinsics)
        vertices = w2c(vertices, cam_extrinsics)
        mesh = trimesh.Trimesh(vertices.copy(), self.faces.copy(),  process=False)
        mesh = pyrender.Mesh.from_trimesh(mesh, material=material)
        if mesh_name in self.mesh_nodes:
            self.scene.remove_node(self.mesh_nodes[mesh_name])
            del self.mesh_nodes[mesh_name]

        self.mesh_nodes[mesh_name] = self.scene.add(mesh)

        return points2d_proj


    def render(self, smplx_out, frame_n, cam_extrinsics, cam_intrinsics, img_fn, smplx_pred=None,
               save_name="test.png", scale_img=3, padding=0, output_size=768,
               max_size=None):
        img_bgr = cv2.imread(img_fn)
        input_img = img_bgr.copy()
        img_h, img_w, _ = img_bgr.shape

        gt_ldmks = self.add_mesh(smplx_out, frame_n, cam_extrinsics, cam_intrinsics,
                                  color_name="pink")

        renderer = pyrender.OffscreenRenderer(img_w, img_h)
        color, _ = renderer.render(self.scene, flags=pyrender.RenderFlags.RGBA)

        alpha_ch = color[..., 3] / 255.0
        color_rgb = color[..., :3] * alpha_ch[..., None] + (1 - alpha_ch[..., None]) * img_bgr
        color_rgb = color_rgb.astype(np.uint8)
        # combine color and img_bgr
        alpha = 0.25  # less alpha means mesh is more visible
        color_rgb = cv2.addWeighted(img_bgr, alpha, color_rgb, (1-alpha), 0)

        if self.mesh_nodes:
            for mesh_name, value in self.mesh_nodes.items():
                self.scene.remove_node(value)
            self.mesh_nodes = {}
        renderer.delete()

        renderer = pyrender.OffscreenRenderer(img_w, img_h)
        gt_ldmks = gt_ldmks[:, :2]
        x_min, x_max = gt_ldmks[:, 0].min(), gt_ldmks[:, 0].max()
        y_min, y_max = gt_ldmks[:, 1].min(), gt_ldmks[:, 1].max()
        x_min = max(0, int(x_min - padding * (x_max - x_min)))
        x_max = min(img_w, int(x_max + padding * (x_max - x_min)))
        y_min = max(0, int(y_min - padding * (y_max - y_min)))
        y_max = min(img_h, int(y_max + padding * (y_max - y_min)))
        if max_size is not None:
            x_min = x_min - (max_size - (x_max - x_min)) // 2
            x_max = x_max + (max_size - (x_max - x_min)) // 2
            y_min = y_min - (max_size - (y_max - y_min)) // 2
            y_max = y_max + (max_size - (y_max - y_min)) // 2
            x_min = np.max([0, x_min])
            x_max = np.min([img_w, x_max])
            y_min = np.max([0, y_min])
            y_max = np.min([img_h, y_max])
        if (x_max-x_min < 10) or (y_max-y_min < 10) or not is_bbx_overlap((x_min, y_min, x_max, y_max), (0, 0, img_w, img_h)):
            color_rgb = np.zeros((output_size, output_size, 3))
            input_img = color_rgb.copy()
            if smplx_pred is not None:
                color_rgb_pred = np.zeros((output_size, output_size, 3))
        else:
            color_rgb = color_rgb[y_min:y_max, x_min:x_max]
            input_img = input_img[y_min:y_max, x_min:x_max]
            if smplx_pred is not None:
                pred_ldmks = self.add_mesh(smplx_pred, frame_n, cam_extrinsics, cam_intrinsics,
                                            mesh_name="mesh_pred", color_name="blue")
                color, _ = renderer.render(self.scene, flags=pyrender.RenderFlags.RGBA)

                alpha_ch = color[..., 3] / 255.0
                color_rgb_pred = color[..., :3] * alpha_ch[..., None] + (1 - alpha_ch[..., None]) * img_bgr
                color_rgb_pred = color_rgb_pred.astype(np.uint8)
                # combine color and img_bgr
                color_rgb_pred = cv2.addWeighted(img_bgr, alpha, color_rgb_pred, (1-alpha), 0)
                color_rgb_pred = color_rgb_pred[y_min:y_max, x_min:x_max]
        highest_val = max(color_rgb.shape[:2])
        scale = scale_img #highest_val / output_size
        resize_img = False  # CHANGE to tru to make video maybe
        if resize_img:
            color_rgb = cv2.copyMakeBorder(color_rgb, 0, max_size - color_rgb.shape[0], max_size - color_rgb.shape[1], 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
            color_rgb = cv2.resize(color_rgb, (int(color_rgb.shape[1]/scale), int(color_rgb.shape[0]/scale)))

            input_img = cv2.copyMakeBorder(input_img, 0, max_size - input_img.shape[0], max_size - input_img.shape[1], 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
            input_img = cv2.resize(input_img, (int(input_img.shape[1]/scale), int(input_img.shape[0]/scale)))

        if smplx_pred is not None:
            if resize_img:
                color_rgb_pred = cv2.copyMakeBorder(color_rgb_pred, 0, max_size - color_rgb_pred.shape[0], 0, max_size - color_rgb_pred.shape[1], cv2.BORDER_CONSTANT, value=[0, 0, 0])
                color_rgb_pred = cv2.resize(color_rgb_pred, (int(color_rgb_pred.shape[1]/scale), int(color_rgb_pred.shape[0]/scale)))
            # pad the image to output_sizexoutput_size
            save_name_base = os.path.basename(save_name)
            save_name_dir = os.path.dirname(save_name)
            save_name_input = os.path.join(save_name_dir, "input_"+save_name_base)
            save_name_gt = os.path.join(save_name_dir, "gt_"+save_name_base)
            save_name_pred = os.path.join(save_name_dir, "pred_"+save_name_base)
            cv2.imwrite(save_name_input, input_img)
            cv2.imwrite(save_name_gt, color_rgb)
            cv2.imwrite(save_name_pred, color_rgb_pred)

            color_rgb = np.concatenate([input_img, color_rgb, color_rgb_pred], axis=1)

        else:
            color_rgb = np.concatenate([input_img, color_rgb], axis=1)

        if self.mesh_nodes:
            for mesh_name, value in self.mesh_nodes.items():
                self.scene.remove_node(value)
            self.mesh_nodes = {}
        renderer.delete()

        cv2.imwrite(save_name, color_rgb)


