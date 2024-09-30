import tempfile
import json
import os
import uuid
import logging
import aiohttp
import asyncio

from concurrent.futures import ThreadPoolExecutor
from opentelemetry.sdk.trace.export import SpanExporter
from ..utils import get_unique_key
from .raga_exporter import RagaExporter

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileSpanExporter(SpanExporter):
    def __init__(
        self,
        project_name=None,
        session_id=None,
        metadata=None,
        pipeline=None,
        raga_client=None,
    ):
        """
        Initializes the FileSpanExporter.

        Args:
            project_name (str, optional): The name of the project. Defaults to None.
            session_id (str, optional): The session ID. Defaults to None.
            metadata (dict, optional): Metadata information. Defaults to None.
            pipeline (dict, optional): The pipeline configuration. Defaults to None.

        Returns:
            None
        """
        self.project_name = project_name
        self.session_id = session_id if session_id is not None else str(uuid.uuid4())
        self.metadata = metadata
        self.pipeline = pipeline
        self.sync_file = None
        # Set the temp directory to be output dir
        os.makedirs(
            os.path.join(tempfile.gettempdir(), "raga_temp", "backup"), exist_ok=True
        )
        self.dir_name = os.path.join(tempfile.gettempdir(), "raga_temp")
        self.raga_client = raga_client

    def export(self, spans):
        """
        Export spans to a JSON file with additional metadata and pipeline information.

        Args:
            spans (list): List of spans to be exported.

        Returns:
            None
        """
        traces_list = [json.loads(span.to_json()) for span in spans]
        trace_id = traces_list[0]["context"]["trace_id"]

        self.filename = os.path.join(self.dir_name, trace_id + ".jsonl")

        # add the ids
        self.metadata["id"] = get_unique_key(self.metadata)
        self.pipeline["id"] = get_unique_key(self.pipeline)

        # add prompt id to each trace in trace_list
        for t in traces_list:
            t["prompt_id"] = get_unique_key(t)

        export_data = {
            "project_name": self.project_name,
            "trace_id": trace_id,
            "session_id": self.session_id,
            "traces": traces_list,
            "metadata": self.metadata,
            "pipeline": self.pipeline,
        }

        json_file_path = os.path.join(self.dir_name, trace_id + ".json")
        with open(self.filename, "a", encoding="utf-8") as f:
            logger.debug(f"Writing jsonl file: {self.filename}")
            f.write(json.dumps(export_data) + "\n")

        # Write export_data to a JSON file named tracer.json in the current working directory
        tracer_json_path = os.path.join(os.getcwd(), "tracer.json")
        with open(tracer_json_path, "w", encoding="utf-8") as tracer_file:
            logger.debug(f"Writing json file: {tracer_json_path}")
            json.dump(export_data, tracer_file, ensure_ascii=False, indent=4)
        
        

        if os.path.exists(json_file_path):
            with open(json_file_path, "r") as f:
                data = json.load(f)
                data.append(export_data)
            with open(json_file_path, "w") as f:
                logger.debug(f"Appending to json file: {json_file_path}")
                json.dump(data, f)
        else:
            with open(json_file_path, "w") as f:
                logger.debug(f"Writing json  file: {json_file_path}")
                json_data = [export_data]
                json.dump(json_data, f)
                if self.sync_file is not None:
                    # self._upload_task = self._run_async(self._upload_traces(json_file_path= self.sync_file))
                    self._run_async(self._upload_traces(json_file_path=self.sync_file))
                self.sync_file = json_file_path

        # asyncio.run(self.server_upload(json_file_path))

    def _run_async(self, coroutine):
        """Run an asynchronous coroutine in a separate thread."""
        loop = asyncio.new_event_loop()
        with ThreadPoolExecutor() as executor:
            future = executor.submit(lambda: loop.run_until_complete(coroutine))
        return future.result()

    async def _upload_traces(self, json_file_path=None):
        """
        Asynchronously uploads traces to the RagaAICatalyst server.

        This function uploads the traces generated by the RagaAICatalyst client to the RagaAICatalyst server. It uses the `aiohttp` library to make an asynchronous HTTP request to the server. The function first checks if the `RAGAAI_CATALYST_TOKEN` environment variable is set. If not, it raises a `ValueError` with the message "RAGAAI_CATALYST_TOKEN not found. Cannot upload traces.".

        The function then uses the `asyncio.wait_for` function to wait for the `check_and_upload_files` method of the `raga_client` object to complete. The `check_and_upload_files` method is called with the `session` object and a list of file paths to be uploaded. The `timeout` parameter is set to the value of the `upload_timeout` attribute of the `Tracer` object.

        If the upload is successful, the function returns the string "Files uploaded successfully" if the `upload_stat` variable is truthy, otherwise it returns the string "No files to upload".

        If the upload times out, the function returns a string with the message "Upload timed out after {self.upload_timeout} seconds".

        If any other exception occurs during the upload, the function returns a string with the message "Upload failed: {str(e)}", where `{str(e)}` is the string representation of the exception.

        Parameters:
            None

        Returns:
            A string indicating the status of the upload.
        """
        async with aiohttp.ClientSession() as session:
            if not os.getenv("RAGAAI_CATALYST_TOKEN"):
                raise ValueError(
                    "RAGAAI_CATALYST_TOKEN not found. Cannot upload traces."
                )

            try:
                upload_stat = await self.raga_client.check_and_upload_files(
                    session=session,
                    file_paths=[json_file_path],
                )
                return (
                    "Files uploaded successfully"
                    if upload_stat
                    else "No files to upload"
                )
            except asyncio.TimeoutError:
                return f"Upload timed out after {self.upload_timeout} seconds"
            except Exception as e:
                return f"Upload failed: {str(e)}"

    def shutdown(self):
        pass
