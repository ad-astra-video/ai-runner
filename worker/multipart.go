package worker

import (
	"fmt"
	"io"
	"mime/multipart"
	"strconv"
)

func NewImageToImageMultipartWriter(w io.Writer, req ImageToImageMultipartRequestBody) (*multipart.Writer, error) {
	mw := multipart.NewWriter(w)
	writer, err := mw.CreateFormFile("image", req.Image.Filename())
	if err != nil {
		return nil, err
	}
	imageSize := req.Image.FileSize()
	imageRdr, err := req.Image.Reader()
	if err != nil {
		return nil, err
	}
	copied, err := io.Copy(writer, imageRdr)
	if err != nil {
		return nil, err
	}
	if copied != imageSize {
		return nil, fmt.Errorf("failed to copy image to multipart request imageBytes=%v copiedBytes=%v", imageSize, copied)
	}

	if err := mw.WriteField("prompt", req.Prompt); err != nil {
		return nil, err
	}
	if req.ModelId != nil {
		if err := mw.WriteField("model_id", *req.ModelId); err != nil {
			return nil, err
		}
	}
	if req.Strength != nil {
		if err := mw.WriteField("strength", fmt.Sprintf("%f", *req.Strength)); err != nil {
			return nil, err
		}
	}
	if req.GuidanceScale != nil {
		if err := mw.WriteField("guidance_scale", fmt.Sprintf("%f", *req.GuidanceScale)); err != nil {
			return nil, err
		}
	}
	if req.NegativePrompt != nil {
		if err := mw.WriteField("negative_prompt", *req.NegativePrompt); err != nil {
			return nil, err
		}
	}
	if req.Seed != nil {
		if err := mw.WriteField("seed", strconv.Itoa(*req.Seed)); err != nil {
			return nil, err
		}
	}

	if err := mw.Close(); err != nil {
		return nil, err
	}

	return mw, nil
}

func NewImageToVideoMultipartWriter(w io.Writer, req ImageToVideoMultipartRequestBody) (*multipart.Writer, error) {
	mw := multipart.NewWriter(w)
	writer, err := mw.CreateFormFile("image", req.Image.Filename())
	if err != nil {
		return nil, err
	}
	imageSize := req.Image.FileSize()
	imageRdr, err := req.Image.Reader()
	if err != nil {
		return nil, err
	}
	copied, err := io.Copy(writer, imageRdr)
	if err != nil {
		return nil, err
	}
	if copied != imageSize {
		return nil, fmt.Errorf("failed to copy image to multipart request imageBytes=%v copiedBytes=%v", imageSize, copied)
	}

	if req.ModelId != nil {
		if err := mw.WriteField("model_id", *req.ModelId); err != nil {
			return nil, err
		}
	}
	if req.Height != nil {
		if err := mw.WriteField("height", strconv.Itoa(*req.Height)); err != nil {
			return nil, err
		}
	}
	if req.Width != nil {
		if err := mw.WriteField("width", strconv.Itoa(*req.Width)); err != nil {
			return nil, err
		}
	}
	if req.Fps != nil {
		if err := mw.WriteField("fps", strconv.Itoa(*req.Fps)); err != nil {
			return nil, err
		}
	}
	if req.MotionBucketId != nil {
		if err := mw.WriteField("motion_bucket_id", strconv.Itoa(*req.MotionBucketId)); err != nil {
			return nil, err
		}
	}
	if req.NoiseAugStrength != nil {
		if err := mw.WriteField("noise_aug_strength", fmt.Sprintf("%f", *req.NoiseAugStrength)); err != nil {
			return nil, err
		}
	}
	if req.Seed != nil {
		if err := mw.WriteField("seed", strconv.Itoa(*req.Seed)); err != nil {
			return nil, err
		}
	}

	if err := mw.Close(); err != nil {
		return nil, err
	}

	return mw, nil
}
