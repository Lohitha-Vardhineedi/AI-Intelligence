import { createAction, createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { apiUrl } from "@/lib/config";
import { errorMessage } from "@/lib/errors";
import { uploadFile } from "@/lib/upload";
import { videosApi } from "@/services/videosApi";
import type { Video } from "@/types/video";

type UploadStatus = "idle" | "uploading" | "starting" | "failed";

interface VideoState {
  upload: {
    status: UploadStatus;
    fileName: string | null;
    progress: number; // 0-100
    error: string | null;
  };
}

const initialState: VideoState = {
  upload: { status: "idle", fileName: null, progress: 0, error: null },
};

const uploadProgressed = createAction<number>("video/uploadProgressed");
const uploadFinished = createAction("video/uploadFinished");

/** Uploads a video, then queues it for analysis. Resolves with the new video. */
export const uploadVideo = createAsyncThunk<Video, File, { rejectValue: string }>(
  "video/upload",
  async (file, { dispatch, signal, rejectWithValue }) => {
    try {
      const video = await uploadFile<Video>(
        apiUrl("/videos/upload"),
        file,
        (percent) => dispatch(uploadProgressed(percent)),
        signal,
      );
      dispatch(uploadFinished());
      // The video now exists even if queueing it fails below, so refresh the list.
      dispatch(videosApi.util.invalidateTags([{ type: "Video", id: "LIST" }]));
      await dispatch(videosApi.endpoints.processVideo.initiate(video.id)).unwrap();
      return video;
    } catch (error) {
      return rejectWithValue(errorMessage(error));
    }
  },
);

const videoSlice = createSlice({
  name: "video",
  initialState,
  reducers: {
    resetUpload: (state) => {
      state.upload = initialState.upload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(uploadVideo.pending, (state, action) => {
        state.upload = { status: "uploading", fileName: action.meta.arg.name, progress: 0, error: null };
      })
      .addCase(uploadProgressed, (state, action) => {
        state.upload.progress = action.payload;
      })
      .addCase(uploadFinished, (state) => {
        state.upload.status = "starting";
        state.upload.progress = 100;
      })
      .addCase(uploadVideo.fulfilled, (state) => {
        state.upload = initialState.upload;
      })
      .addCase(uploadVideo.rejected, (state, action) => {
        if (action.meta.aborted) {
          state.upload = initialState.upload;
        } else {
          state.upload.status = "failed";
          state.upload.error = action.payload ?? "Upload failed";
        }
      });
  },
});

export const { resetUpload } = videoSlice.actions;
export default videoSlice.reducer;
