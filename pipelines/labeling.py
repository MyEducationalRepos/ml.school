import logging
import sys

from common import PYTHON
from metaflow import (
    FlowSpec,
    Parameter,
    project,
    pypi_base,
    step,
)
from sagemaker import load_unlabeled_collected_data

logger = logging.getLogger(__name__)


@project(name="penguins")
@pypi_base(
    python=PYTHON,
    packages={
        "pandas": "2.2.2",
        "numpy": "1.26.4",
        "boto3": "1.35.15",
    },
)
class Labeling(FlowSpec):
    """A labeling pipeline to generate fake, automatic ground truth labels.

    This pipeline generates fake labels for any data collected by a hosted model.
    Of course, this is only useful for testing the monitoring process. In a production
    environment, you would need an actual labeling process (manual or automatic) to
    generate ground truth data.
    """

    datastore_uri = Parameter(
        "datastore-uri",
        help=(
            "The location where the data collected by the hosted model is stored. This "
            "pipeline supports using data stored in a SQLite database, or data "
            "captured by a SageMaker endpoint and stored in S3."
        ),
        required=True,
    )

    ground_truth_uri = Parameter(
        "ground-truth-uri",
        help=(
            "When labeling data captured by a SageMaker endpoint, this parameter "
            "specifies the S3 location where the ground truth labels are stored. "
        ),
        required=False,
    )

    ground_truth_quality = Parameter(
        "ground-truth-quality",
        help=("The quality of the ground truth labels."),
        default=0.8,
    )

    @step
    def start(self):
        self.next(self.label)

    @step
    def label(self):
        if self.datastore_uri.startswith("s3://"):
            self._label_sagemaker_data()
        elif self.datastore_uri.startswith("sqlite://"):
            pass
        else:
            message = (
                "Invalid datastore location. Must be an S3 location in the "
                "format `s3://bucket/prefix` or a SQLite database file in the format "
                "`sqlite:///path/to/database.db`"
            )
            raise ValueError(message)

        self.next(self.end)

    @step
    def end(self):
        pass

    def _label_sagemaker_data(self):
        import json
        import random
        from datetime import datetime, timezone

        import boto3

        if not self.ground_truth_uri:
            message = "The 'ground-truth-uri' parameter is required."
            raise RuntimeError(message)

        s3_client = boto3.client("s3")

        data = load_unlabeled_collected_data(
            s3_client,
            self.datastore_uri,
            self.ground_truth_uri,
        )

        if data.empty:
            return

        records = []

        for event_id, group in data.groupby("event_id"):
            predictions = []
            for _, row in group.iterrows():
                predictions.append(
                    row["prediction"]
                    if random.random() < self.ground_truth_quality
                    else random.choice(["Adelie", "Chinstrap", "Gentoo"]),
                )

            record = {
                "groundTruthData": {
                    # For testing purposes, we will generate a random
                    # label for each request.
                    "data": predictions,
                    "encoding": "CSV",
                },
                "eventMetadata": {
                    # This value should match the id of the request
                    # captured by the endpoint.
                    "eventId": event_id,
                },
                "eventVersion": "0",
            }

            records.append(json.dumps(record))

        ground_truth_payload = "\n".join(records)
        upload_time = datetime.now(tz=timezone.utc)
        uri = (
            "/".join(self.ground_truth_uri.split("/")[3:])
            + f"{upload_time:%Y/%m/%d/%H/%M%S}.jsonl"
        )

        s3_client.put_object(
            Body=ground_truth_payload,
            Bucket=self.ground_truth_uri.split("/")[2],
            Key=uri,
        )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        level=logging.INFO,
    )
    Labeling()
