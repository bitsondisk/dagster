import datetime
import operator
from typing import TYPE_CHECKING, AbstractSet, Any, Callable, Optional

import dagster._check as check
from dagster._core.definitions.asset_subset import AssetSubset, AssetSubsetSerializer
from dagster._core.definitions.events import AssetKey, AssetKeyPartitionKey
from dagster._core.definitions.partition import AllPartitionsSubset, PartitionsDefinition
from dagster._core.definitions.time_window_partitions import BaseTimeWindowPartitionsSubset
from dagster._serdes.serdes import whitelist_for_serdes

if TYPE_CHECKING:
    from dagster._core.instance import DynamicPartitionsStore


@whitelist_for_serdes(serializer=AssetSubsetSerializer)
class ValidAssetSubset(AssetSubset):
    """Legacy construct used for doing operations over AssetSubsets that are known to be valid. This
    functionality is subsumed by AssetSlice.
    """

    def inverse(
        self,
        partitions_def: Optional[PartitionsDefinition],
        current_time: Optional[datetime.datetime] = None,
        dynamic_partitions_store: Optional["DynamicPartitionsStore"] = None,
    ) -> "ValidAssetSubset":
        """Returns the AssetSubset containing all asset partitions which are not in this AssetSubset."""
        if partitions_def is None:
            return self._replace(value=not self.bool_value)
        else:
            value = partitions_def.subset_with_partition_keys(
                self.subset_value.get_partition_keys_not_in_subset(
                    partitions_def,
                    current_time=current_time,
                    dynamic_partitions_store=dynamic_partitions_store,
                )
            )
            return self._replace(value=value)

    def _oper(self, other: "ValidAssetSubset", oper: Callable[..., Any]) -> "ValidAssetSubset":
        value = oper(self.value, other.value)
        return self._replace(value=value)

    def __sub__(self, other: AssetSubset) -> "ValidAssetSubset":
        """Returns an AssetSubset representing self.asset_partitions - other.asset_partitions."""
        valid_other = self.get_valid(other)
        if not self.is_partitioned:
            return self._replace(value=self.bool_value and not valid_other.bool_value)
        return self._oper(valid_other, operator.sub)

    def __and__(self, other: AssetSubset) -> "ValidAssetSubset":
        """Returns an AssetSubset representing self.asset_partitions & other.asset_partitions."""
        return self._oper(self.get_valid(other), operator.and_)

    def __or__(self, other: AssetSubset) -> "ValidAssetSubset":
        """Returns an AssetSubset representing self.asset_partitions | other.asset_partitions."""
        return self._oper(self.get_valid(other), operator.or_)

    @staticmethod
    def coerce_from_subset(
        subset: AssetSubset, partitions_def: Optional[PartitionsDefinition]
    ) -> "ValidAssetSubset":
        """Converts an AssetSubset to a ValidAssetSubset by returning a copy of this AssetSubset
        if it is compatible with the given PartitionsDefinition, otherwise returns an empty subset.
        """
        if subset.is_compatible_with_partitions_def(partitions_def):
            return ValidAssetSubset(asset_key=subset.asset_key, value=subset.value)
        else:
            return ValidAssetSubset.empty(subset.asset_key, partitions_def)

    def _is_compatible_with_subset(self, other: "AssetSubset") -> bool:
        if isinstance(other.value, (BaseTimeWindowPartitionsSubset, AllPartitionsSubset)):
            return self.is_compatible_with_partitions_def(other.value.partitions_def)
        else:
            return self.is_partitioned == other.is_partitioned

    def get_valid(self, other: AssetSubset) -> "ValidAssetSubset":
        """Creates a ValidAssetSubset from the given AssetSubset by returning a replace of the given
        AssetSubset if it is compatible with this AssetSubset, otherwise returns an empty subset.
        """
        if isinstance(other, ValidAssetSubset):
            return other
        elif self._is_compatible_with_subset(other):
            return ValidAssetSubset(asset_key=other.asset_key, value=other.value)
        else:
            return self._replace(
                # unfortunately, this is the best way to get an empty partitions subset of an unknown
                # type if you don't have access to the partitions definition
                value=(self.subset_value - self.subset_value) if self.is_partitioned else False,
            )

    @staticmethod
    def all(
        asset_key: AssetKey,
        partitions_def: Optional[PartitionsDefinition],
        dynamic_partitions_store: Optional["DynamicPartitionsStore"] = None,
        current_time: Optional[datetime.datetime] = None,
    ) -> "ValidAssetSubset":
        if partitions_def is None:
            return ValidAssetSubset(asset_key=asset_key, value=True)
        else:
            if dynamic_partitions_store is None or current_time is None:
                check.failed(
                    "Must provide dynamic_partitions_store and current_time for partitioned assets."
                )
            return ValidAssetSubset(
                asset_key=asset_key,
                value=AllPartitionsSubset(partitions_def, dynamic_partitions_store, current_time),
            )

    @staticmethod
    def empty(
        asset_key: AssetKey, partitions_def: Optional[PartitionsDefinition]
    ) -> "ValidAssetSubset":
        if partitions_def is None:
            return ValidAssetSubset(asset_key=asset_key, value=False)
        else:
            return ValidAssetSubset(asset_key=asset_key, value=partitions_def.empty_subset())

    @staticmethod
    def from_asset_partitions_set(
        asset_key: AssetKey,
        partitions_def: Optional[PartitionsDefinition],
        asset_partitions_set: AbstractSet[AssetKeyPartitionKey],
    ) -> "ValidAssetSubset":
        return (
            ValidAssetSubset.from_partition_keys(
                asset_key=asset_key,
                partitions_def=partitions_def,
                partition_keys={
                    ap.partition_key for ap in asset_partitions_set if ap.partition_key is not None
                },
            )
            if partitions_def
            else ValidAssetSubset(asset_key=asset_key, value=bool(asset_partitions_set))
        )

    @staticmethod
    def from_partition_keys(
        asset_key: AssetKey,
        partitions_def: PartitionsDefinition,
        partition_keys: AbstractSet[str],
    ) -> "ValidAssetSubset":
        return ValidAssetSubset(
            asset_key=asset_key, value=partitions_def.subset_with_partition_keys(partition_keys)
        )