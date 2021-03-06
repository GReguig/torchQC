import torch
from segmentation.metrics.utils import mean_metric
from segmentation.utils import to_numpy
from scipy.ndimage.morphology import distance_transform_edt
import numpy as np


def _get_border(volume, cut=0.5, dim=3):
    ref = (volume > cut).float()
    border = torch.zeros_like(volume)
    spatial_shape = ref.shape[-dim:]

    for i in range(dim):
        shape = list(spatial_shape)
        shape[i] = 1
        zeros = torch.zeros(shape, device=volume.device)

        slices = [slice(1 * (i == j), spatial_shape[j] + 1 * (i == j)) for j in range(dim)]
        concat = torch.cat([ref, zeros], dim=i)[slices]
        border[(ref - concat) == 1] = 1

        slices = [slice(spatial_shape[j]) for j in range(dim)]
        concat = torch.cat([zeros, ref], dim=i)[slices]
        border[(ref - concat) == 1] = 1

    return border


class DistanceMetric:
    def __init__(self, cut=0.5, radius=5):
        self.cut = cut
        self.radius = radius
        self.dim = 3
        self.d_max = torch.tensor(self.radius).float()
        self.distance_map = self._get_distance_map()
        self.distances = self.distance_map.unique()
        self.distance_kernels = self._get_distance_kernels()

    def _get_distance_map(self):
        distance_range = torch.arange(-self.radius, self.radius + 1)
        distance_grid = torch.meshgrid([distance_range for _ in range(self.dim)])
        distance_map = sum([distance_grid[i].flatten() ** 2 for i in range(self.dim)]).float().sqrt()
        distance_map[distance_map > self.radius] = self.radius
        return distance_map

    def _get_distance_kernels(self):
        kernels = torch.zeros(len(self.distances), 1, *[2 * self.radius + 1 for _ in range(self.dim)])

        for idx in range(len(self.distances)):
            kernel = self.distance_map == self.distances[idx]
            kernels[idx] = kernel.reshape(1, *[2 * self.radius + 1 for _ in range(self.dim)])

        return kernels

    def _pairwise_distances(self, x, y, single_kernel=False):
        device = x.device
        kernels = self.distance_kernels.to(device)
        if single_kernel:
            kernels = kernels[:-1].sum(dim=0, keepdim=True)

        # Compute distances to y points
        distances_to_y = torch.conv3d(
            y.float().expand(1, 1, -1, -1, -1),
            kernels,
            padding=self.radius
        )[0]

        # Remove zero points from x
        relevant_distances = distances_to_y.permute(1, 2, 3, 0)[
            x.nonzero(as_tuple=True)
        ]

        # Compute distances from convolution values
        all_distances = torch.zeros_like(relevant_distances)
        indices = relevant_distances.nonzero(as_tuple=True)
        all_distances[all_distances == 0] = self.d_max.to(device)
        all_distances[indices] = self.distances[indices[1]].to(device)

        return all_distances

    def average_hausdorff_distance(self, prediction, target):
        prediction = prediction > self.cut
        target = target > self.cut

        prediction_mask = prediction.clone()
        prediction_mask[prediction * target] = 0
        target_mask = _get_border(target)

        if prediction_mask.sum():
            min_dist, _ = self._pairwise_distances(
                prediction_mask, target_mask
            ).min(dim=1)
            first_term = min_dist.sum() / prediction.sum()
        else:
            first_term = 0.

        prediction_mask = _get_border(prediction)
        target_mask = target.clone()
        target_mask[prediction * target] = 0

        if target_mask.sum():
            min_dist, _ = self._pairwise_distances(
                target_mask, prediction_mask
            ).min(dim=1)
            second_term = min_dist.sum() / target.sum()
        else:
            second_term = 0.

        return first_term + second_term

    def amount_of_far_points(self, prediction, target):
        prediction = prediction > self.cut
        target = target > self.cut

        prediction_mask = prediction.clone()
        prediction_mask[prediction * target] = 0
        target_mask = _get_border(target)

        if prediction_mask.sum():
            min_dist, _ = self._pairwise_distances(
                prediction_mask, target_mask, single_kernel=True
            ).min(dim=1)
            return (min_dist >= self.radius).sum()
        else:
            return 0.

    def batch_average_hausdorff_distance(self, prediction, target):
        res = 0.
        for p, t in zip(prediction, target):
            res += self.average_hausdorff_distance(p, t)
        return res

    def batch_amount_of_far_points(self, prediction, target):
        res = 0.
        for p, t in zip(prediction, target):
            res += self.amount_of_far_points(p, t)
        return res

    def mean_average_hausdorff_distance(self, prediction, target):
        return mean_metric(
            prediction, target, self.batch_average_hausdorff_distance
        )

    def mean_amount_of_far_points(self, prediction, target):
        return mean_metric(
            prediction, target, self.batch_amount_of_far_points
        )

    @staticmethod
    def surface_distances(x, y):
        """ From
        https://github.com/BBillot/SynthSeg/blob/master/SynthSeg/evaluate.py
        Computes the average boundary distance of two masks.
        x and y should be boolean or 0/1 numpy arrays of the same size."""

        assert x.shape == y.shape, 'both inputs should have same size, ' \
                                   f'had {x.shape} and {y.shape}'

        x = to_numpy(x)
        y = to_numpy(y)

        # detect edge
        x_dist_int = distance_transform_edt(x * 1)
        x_edge = (x_dist_int == 1) * 1
        y_dist_int = distance_transform_edt(y * 1)
        y_edge = (y_dist_int == 1) * 1

        # calculate distance from edge
        x_dist = distance_transform_edt(np.logical_not(x_edge))
        y_dist = distance_transform_edt(np.logical_not(y_edge))

        # find distances from the 2 surfaces
        x_dists_to_y = y_dist[x_edge == 1]
        y_dists_to_x = x_dist[y_edge == 1]

        # find average distance between 2 surfaces
        x_mean_dist_to_y = np.mean(x_dists_to_y)
        y_mean_dist_to_x = np.mean(y_dists_to_x)

        return (x_mean_dist_to_y + y_mean_dist_to_x) / 2
