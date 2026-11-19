"""Pretrained DINOv2 small-model image embeddings."""
from pathlib import Path
from typing import Iterable


MODEL_NAME = "dinov2_vits14"
EMBEDDING_DIMENSION = 384
IMAGE_SIZE = 224
IMAGE_MEAN = (0.485, 0.456, 0.406)
IMAGE_STD = (0.229, 0.224, 0.225)


class DINOv2EmbeddingService:
    """Load a pretrained DINOv2 ViT-S/14 model and embed image batches."""

    def __init__(self, device: str = "auto") -> None:
        import torch
        from torchvision import transforms
        from torchvision.transforms import InterpolationMode

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")

        self.torch = torch
        self.device = torch.device(device)
        from app.core.models_safe import load_dinov2_vits14

        # vendored code + SHA-256-verified weights: no remote code is downloaded or executed
        self.model = load_dinov2_vits14()
        self.model.eval().to(self.device)
        self.preprocess = transforms.Compose(
            [
                transforms.Resize(256, interpolation=InterpolationMode.BICUBIC),
                transforms.CenterCrop(IMAGE_SIZE),
                transforms.ToTensor(),
                transforms.Normalize(IMAGE_MEAN, IMAGE_STD),
            ]
        )

    def preprocess_images(self, images: Iterable[object]):
        """Convert RGB PIL images to a model-ready batch tensor."""
        return self.torch.stack([self.preprocess(image) for image in images])

    def embed_tensor(self, batch):
        """Return L2-normalized class-token vectors for a preprocessed batch."""
        batch = batch.to(self.device, non_blocking=True)
        with self.torch.inference_mode():
            features = self.model.forward_features(batch)
            vectors = features["x_norm_clstoken"]
            vectors = self.torch.nn.functional.normalize(vectors, p=2, dim=1)
        return vectors.detach().cpu().numpy()

    def embed_images(self, images: Iterable[object]):
        return self.embed_tensor(self.preprocess_images(images))

    @staticmethod
    def load_rgb_image(path: str | Path):
        from PIL import Image

        with Image.open(path) as image:
            return image.convert("RGB")